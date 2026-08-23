"""Machine-readable reasons on every decision.

The `alternatives` reason is what makes an operator trust the system: it shows
what was rejected and on what grounds. The unserved explanation matters more -
silence about a demand nobody is coming for is how people get missed.
"""

from __future__ import annotations

from pharos_core import Reason, TaskKind

from .objective import SolverConfig, Weights, demand_unit_value


def justify_assignment(
    d,
    a,
    cm,
    config: SolverConfig,
    w: Weights,
    zone_index: dict,
    kind=TaskKind.RESCUE,
    eligible_assets: set[str] | None = None,
) -> list[Reason]:
    travel_min = (cm.get(a.asset_id, d.demand_id) or 0.0) / 60.0
    reasons: list[Reason] = []

    if kind is TaskKind.VERIFICATION:
        reasons.append(
            Reason(
                factor="dispatch_class",
                value="verification",
                contribution=None,
            )
        )
        reasons.append(
            Reason(
                factor="why_not_rescue",
                value=(
                    f"headcount confidence {d.quantity_confidence:.2f} and trust "
                    f"{d.trust_score:.2f}; below the thresholds for committing an asset "
                    f"({config.verify_threshold:.2f} / {config.trust_threshold:.2f}). "
                    f"A {int(travel_min)}-minute callback resolves this for the cost of "
                    f"a phone call rather than a boat."
                ),
            )
        )
        reasons.append(
            Reason(
                factor="potential_value",
                value=f"up to {d.need.people_upper} people if confirmed",
            )
        )
        return reasons

    unit = demand_unit_value(d, w)
    headcount = d.need.people_lower if config.use_confidence else d.need.people
    base = unit * headcount
    total = max(base, 1e-6)

    reasons.append(
        Reason(
            factor="urgency",
            value=f"{d.need.type.value}, {d.need.medical_urgency.value}",
            contribution=round(unit * headcount / total, 3),
        )
    )
    reasons.append(
        Reason(
            factor="headcount",
            value=(
                f"{d.need.people_lower}-{d.need.people_upper} people "
                f"(committed {d.need.people_upper if config.use_confidence else d.need.people} "
                f"seats, credited {headcount})"
            ),
        )
    )
    if d.need.vulnerability_flags:
        reasons.append(
            Reason(factor="vulnerability", value=", ".join(sorted(d.need.vulnerability_flags)))
        )
    if config.use_trust:
        reasons.append(
            Reason(
                factor="trust",
                value=(
                    f"{d.trust_score:.2f} from {d.duplicate_collapse_count} report(s) "
                    f"across {len(set(d.channels)) or 1} channel(s)"
                ),
                contribution=round(d.trust_score, 3),
            )
        )
    reasons.append(
        Reason(
            factor="reachability",
            value=(
                f"{a.type.value} {a.asset_id} reaches this in {travel_min:.0f} min over the "
                f"current road state"
            ),
        )
    )
    reasons.append(
        Reason(
            factor="location_quality",
            value=f"{d.location.resolution.value} resolution via {d.location.method} "
            f"(geo confidence {d.location.geo_confidence:.2f})",
        )
    )
    if config.use_equity and zone_index:
        from .solver import _equity_zone

        zone = _equity_zone(d, config)
        deficit = zone_index.get(zone)
        if deficit is not None:
            reasons.append(
                Reason(
                    factor="zone_deficit",
                    value=(
                        f"zone {zone[:9]} is at {(1.0 - deficit):.0%} coverage; equity control "
                        f"at {config.equity_weight:.2f} weights this demand up "
                        f"{(config.equity_weight * deficit) * 100:.0f}%"
                    ),
                    contribution=round(deficit, 3),
                )
            )

    alt = _alternative(d, a, cm, travel_min, eligible=eligible_assets)
    if alt:
        reasons.append(alt)
    return reasons


def _alternative(d, chosen, cm, chosen_min: float, eligible: set[str] | None = None) -> Reason | None:
    """Name the runner-up and why it lost. This is the trust-building line.

    Only assets that could actually have taken this job. A verification
    operator is three minutes from everything because a phone call costs the
    same from anywhere, and a boat cannot deliver drinking water - listing
    either as the asset that "was closer" is nonsense to an operator and costs
    exactly the trust this panel exists to build.
    """
    others = sorted(
        (t / 60.0, aid)
        for aid, row in cm.cost.items()
        if aid != chosen.asset_id
        and (t := row.get(d.demand_id)) is not None
        and not _is_verifier_id(aid)
        and (eligible is None or aid in eligible)
    )
    if not others:
        return None
    t, aid = others[0]
    if t <= chosen_min:
        return Reason(
            factor="alternatives",
            value=f"{aid} was closer ({t:.0f} min) but was committed elsewhere or out of capacity",
        )
    return Reason(
        factor="alternatives",
        value=f"{aid} rejected: {t:.0f} min versus {chosen_min:.0f} min",
    )


VERIFIER_PREFIXES = ("operator-", "volunteer-")


def _is_verifier_id(asset_id: str) -> bool:
    return asset_id.startswith(VERIFIER_PREFIXES)


def explain_unserved(d, cm, assets, reserve_n: int = 0, config: SolverConfig | None = None):
    """Why this demand has no asset. Never leave it blank."""
    from pharos_core import UnservedDemand

    # The nearest *physical* asset. Telling an operator that a phone line is
    # three minutes from a stranded family is not an explanation.
    physical = [
        (t / 60.0, a)
        for a, row in cm.cost.items()
        if not _is_verifier_id(a) and (t := row.get(d.demand_id)) is not None
    ]
    if physical:
        mins_, aid = min(physical)
        secs = mins_ * 60.0
    else:
        aid, secs = None, None

    if aid is None:
        return UnservedDemand(
            demand_id=d.demand_id,
            explanation=(
                "Unreachable: no available asset can reach this location over the current "
                "road state. Escalate for an air asset or a route survey."
            ),
        )

    mins = secs / 60.0
    if config and config.use_trust and d.trust_score * d.quantity_confidence < config.autodispatch_floor:
        why = (
            f"Below the auto-dispatch floor (trust {d.trust_score:.2f} x confidence "
            f"{d.quantity_confidence:.2f} < {config.autodispatch_floor:.2f}). Held for "
            f"operator review rather than committing an asset."
        )
    elif reserve_n:
        why = (
            f"Nearest asset {aid} is {mins:.0f} min away but the fleet is at committed "
            f"capacity with {reserve_n} asset(s) held in reserve against unconfirmed demand."
        )
    else:
        why = (
            f"Nearest asset {aid} is {mins:.0f} min away; higher-value demand won the "
            f"available capacity this round."
        )

    return UnservedDemand(
        demand_id=d.demand_id,
        explanation=why,
        nearest_asset_id=aid,
        nearest_travel_minutes=round(mins, 1),
    )
