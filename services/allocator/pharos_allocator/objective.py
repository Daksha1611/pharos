"""Objective weights and solver configuration.

Every novelty claim in the project is a flag on SolverConfig. Turning one off
is one row of the ablation table, which is what makes the claims quantified
rather than asserted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pharos_core import MedicalUrgency, NeedType

# What a served person is worth, by medical urgency of the demand.
URGENCY_WEIGHT = {
    MedicalUrgency.NONE: 1.0,
    MedicalUrgency.MILD: 1.4,
    MedicalUrgency.MODERATE: 2.2,
    MedicalUrgency.CRITICAL: 4.0,
}

# Need types differ in how fast harm accrues. Grounded in Sphere response
# priorities: life safety first, then water, then food and shelter.
NEED_WEIGHT = {
    NeedType.EVACUATION: 1.6,
    NeedType.MEDICAL: 1.8,
    NeedType.WATER: 1.2,
    NeedType.FOOD: 0.9,
    NeedType.SHELTER: 1.0,
    NeedType.SANITATION: 0.7,
    NeedType.MISSING_PERSON: 1.5,
    NeedType.INFRASTRUCTURE: 0.6,
}

# Vulnerability raises the value of serving a demand. Additive, capped.
VULNERABILITY_BONUS = {
    "infant": 0.35,
    "elderly": 0.30,
    "pregnant": 0.35,
    "disabled": 0.30,
    "injured": 0.40,
}
MAX_VULNERABILITY_BONUS = 0.9


@dataclass
class Weights:
    urgency: dict = field(default_factory=lambda: dict(URGENCY_WEIGHT))
    need_type: dict = field(default_factory=lambda: dict(NEED_WEIGHT))
    vulnerability: dict = field(default_factory=lambda: dict(VULNERABILITY_BONUS))

    # Cost of a minute of travel, in units of one served person.
    #
    # This is an opportunity cost, not a fuel cost: a sortie 60 minutes out
    # spends the asset for two hours, which is a sortie it cannot fly
    # somewhere else. Swept against the scenario - 0.06 was too myopic and
    # flew long trips, 0.60 was too timid and left the far half of the district
    # unserved.
    time: float = 0.15

    # How much a verification task is worth relative to the uncertainty it
    # resolves. Resolving doubt on a high-potential-value demand is itself
    # worth scheduling.
    verification: float = 0.55

    # Fraction of the fleet available to hold back at maximum uncertainty.
    reserve_factor: float = 0.35


@dataclass
class SolverConfig:
    """One flag per novelty claim. `full()` is the system as pitched."""

    # --- the seam ---------------------------------------------------------
    use_confidence: bool = True  # headcount enters as an interval, not a point
    use_reserve: bool = True  # hold capacity back under uncertainty
    use_verification: bool = True  # uncertainty routes to verification
    use_trust: bool = True  # low trust suppresses commitment
    use_equity: bool = True  # maximin worst-off-zone term
    use_escalation: bool = True  # ageing demand rises in the ordering

    # --- operator controls ------------------------------------------------
    equity_weight: float = 0.5  # 0 = pure throughput, 1 = pure worst-off zone

    # --- thresholds -------------------------------------------------------
    verify_threshold: float = 0.55  # below this confidence, prefer verifying
    trust_threshold: float = 0.40  # below this trust, prefer verifying
    autodispatch_floor: float = 0.30  # below this, never auto-assign an asset
    global_confidence_floor: float = 0.45  # below this, whole plan degrades

    # --- performance ------------------------------------------------------
    time_limit_s: float = 10.0
    top_k_assets: int = 10
    workers: int = 8

    # How many demands enter the model. An operator's screen shows a ranked
    # queue, not every open record, and the solver works the same way: the
    # 2,000th-ranked demand was never going to win a boat this round.
    #
    # This is a hard requirement, not an optimisation. Handing CP-SAT all 3,900
    # open demands built a model with 39,000 booleans, blew the 10-second
    # budget on every replan, and returned whatever feasible solution it
    # happened to hold - which scored *worse* than greedy nearest-asset.
    max_candidate_demands: int = 700

    # The maximin equity term is the single most expensive thing in the model:
    # one constraint per zone, all coupled through one variable. Aggregating to
    # ward-scale hexes and watching only the busiest zones took a replan from
    # 7.3 seconds to something an operator can move a slider against. The
    # reported equity metric stays at full resolution over every zone.
    equity_resolution: int = 7
    equity_max_zones: int = 60

    @classmethod
    def full(cls, **kw) -> SolverConfig:
        return cls(**kw)

    @classmethod
    def ablation(cls, name: str, **kw) -> SolverConfig:
        """Named ablation variants, so the harness and the slide agree."""
        variants = {
            "full": {},
            "no_confidence": {"use_confidence": False, "use_reserve": False},
            "no_reserve": {"use_reserve": False},
            "no_verification": {"use_verification": False},
            "no_trust": {"use_trust": False},
            "no_equity": {"use_equity": False, "equity_weight": 0.0},
            "no_escalation": {"use_escalation": False},
        }
        if name not in variants:
            raise KeyError(f"unknown ablation {name!r}; have {sorted(variants)}")
        return cls(**{**variants[name], **kw})


def demand_unit_value(d, w: Weights) -> float:
    """Value of serving one person from this demand, before headcount."""
    v = w.urgency.get(d.need.medical_urgency, 1.0) * w.need_type.get(d.need.type, 1.0)
    bonus = sum(w.vulnerability.get(f, 0.0) for f in d.need.vulnerability_flags)
    return v * (1.0 + min(bonus, MAX_VULNERABILITY_BONUS))
