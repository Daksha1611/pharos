"""The allocation solve.

Reading order, because the interesting part is small and buried:

  1. Candidate pairs are pruned to the nearest few assets per demand. Every
     asset paired with every demand is how this goes from 10 seconds to 90.
  2. Capacity is planned against `people_upper`; value is counted against
     `people_lower`. Two lines, and they are the whole confidence idea: plan
     for the worst case, count value for the best-confirmed case. An uncertain
     demand therefore costs the same to serve but earns less, so the solver
     prefers confirmed demand without any rule telling it to.
  3. Trust multiplies value. A hoax at trust 0.15 contributes 15% of its
     apparent value and loses to any real demand nearby. Suppressed, not
     deleted - it stays on the operator's screen.
  4. Verification tasks enter the same model with a cheap asset pool. A demand
     is rescued or verified, never both. Uncertainty routes to verification;
     certainty routes to rescue.
  5. Equity weights up demands in zones that have been served less so far.
     This began as a textbook maximin and was replaced after measurement -
     see the note above `_zone_deficits`.
  6. Reserve holds part of the fleet back when the sensing layer is unsure.

Coverage is never a hard constraint. Something must always be droppable, or
the model returns INFEASIBLE at the exact moment an operator needs an answer.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime

import h3
from ortools.sat.python import cp_model
from pharos_core import (
    Assignment,
    DemandStatus,
    Plan,
    PlanMode,
    ReserveDecision,
    TaskKind,
)

from .costmatrix import CostMatrix
from .justify import explain_unserved, justify_assignment
from .objective import SolverConfig, Weights, demand_unit_value

SCALE = 100  # float objective -> integer, rounded once, at the end


def solve(
    demands,
    assets,
    cm: CostMatrix,
    config: SolverConfig | None = None,
    weights: Weights | None = None,
    now: datetime | None = None,
    zone_coverage: dict[str, float] | None = None,
) -> Plan:
    config = config or SolverConfig()
    weights = weights or Weights()
    now = now or datetime.now()
    t0 = time.perf_counter()

    plan = Plan(
        plan_id=f"PLAN-{uuid.uuid4().hex[:10]}",
        created_at=now,
        equity_weight=config.equity_weight,
    )

    active = [d for d in demands if d.status in (DemandStatus.UNASSIGNED, DemandStatus.VERIFYING)]
    available = [a for a in assets if a.is_available]
    if not active or not available:
        plan.solver_status = "EMPTY"
        plan.solve_time_ms = (time.perf_counter() - t0) * 1000.0
        return plan

    # --- graceful degradation ------------------------------------------------
    # If the sensing layer has lost confidence across the board, the correct
    # behaviour is to stop assigning and hand control back, not to guess.
    mean_conf = sum(d.quantity_confidence for d in active) / len(active)
    if mean_conf < config.global_confidence_floor:
        plan.mode = PlanMode.DECISION_SUPPORT
        plan.banner = (
            f"Low confidence across intake (mean {mean_conf:.2f} < "
            f"{config.global_confidence_floor:.2f}) - manual dispatch required"
        )

    physical = [a for a in available if not a.is_verifier]
    verifiers = [a for a in available if a.is_verifier]

    active = _candidate_window(active, cm, config, weights)
    by_id = {d.demand_id: d for d in active}

    m = cp_model.CpModel()

    # ---------------------------------------------------------------------
    # 1. rescue variables, on pruned candidate pairs only
    # ---------------------------------------------------------------------
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    if plan.mode is PlanMode.AUTONOMOUS:
        for d in active:
            if config.use_trust and d.trust_score * d.quantity_confidence < config.autodispatch_floor:
                # Never commit a physical asset below the hard floor. This is
                # the answer to "what if your model is wrong".
                continue
            # Sort on travel time and asset id. Sorting on the bare tuple falls
            # through to comparing Asset objects whenever two assets are the
            # same distance away, which they routinely are when they share a
            # depot.
            cands = sorted(
                (
                    (t, a)
                    for a in physical
                    if (t := cm.get(a.asset_id, d.demand_id)) is not None and _serves(a, d)
                ),
                key=lambda pair: (pair[0], pair[1].asset_id),
            )[: config.top_k_assets]
            for _, a in cands:
                x[d.demand_id, a.asset_id] = m.NewBoolVar(f"x_{d.demand_id}_{a.asset_id}")

    # ---------------------------------------------------------------------
    # 2. verification variables - uncertainty as a dispatch class
    # ---------------------------------------------------------------------
    y: dict[tuple[str, str], cp_model.IntVar] = {}
    if config.use_verification and verifiers:
        for d in active:
            if not _needs_verification(d, config):
                continue
            for v in verifiers:
                y[d.demand_id, v.asset_id] = m.NewBoolVar(f"y_{d.demand_id}_{v.asset_id}")

    if not x and not y:
        plan.solver_status = "NO_CANDIDATES"
        plan.solve_time_ms = (time.perf_counter() - t0) * 1000.0
        plan.unserved = [explain_unserved(d, cm, assets) for d in active]
        return plan

    # ---------------------------------------------------------------------
    # 3. each demand gets at most one action: rescued, or verified, not both
    # ---------------------------------------------------------------------
    per_demand: dict[str, list] = defaultdict(list)
    for (did, _), var in x.items():
        per_demand[did].append(var)
    for (did, _), var in y.items():
        per_demand[did].append(var)
    for vs in per_demand.values():
        m.AddAtMostOne(vs)

    # ---------------------------------------------------------------------
    # 4. capacity. Plan against the UPPER bound - never under-provision.
    # ---------------------------------------------------------------------
    for a in physical:
        terms = [
            var * _capacity_load(by_id[did], config)
            for (did, aid), var in x.items()
            if aid == a.asset_id
        ]
        if terms:
            m.Add(sum(terms) <= a.capacity)

    for v in verifiers:
        terms = [var for (did, aid), var in y.items() if aid == v.asset_id]
        if terms:
            m.Add(sum(terms) <= v.capacity)

    # ---------------------------------------------------------------------
    # 5. reserve hedging - hold the fleet back when sensing is unsure
    # ---------------------------------------------------------------------
    reserve_n = 0
    if config.use_reserve and physical:
        uncertainty = 1.0 - mean_conf
        reserve_n = int(len(physical) * weights.reserve_factor * uncertainty)
        if reserve_n > 0:
            used = {}
            for a in physical:
                u = m.NewBoolVar(f"used_{a.asset_id}")
                used[a.asset_id] = u
                for (_did, aid), var in x.items():
                    if aid == a.asset_id:
                        m.Add(var <= u)
            m.Add(sum(used.values()) <= len(physical) - reserve_n)
            plan.reserve = ReserveDecision(
                assets_held=reserve_n,
                total_assets=len(physical),
                mean_confidence=round(mean_conf, 3),
                rationale=(
                    f"Mean headcount confidence {mean_conf:.2f}; holding {reserve_n} of "
                    f"{len(physical)} assets against demand not yet corroborated."
                ),
            )

    # ---------------------------------------------------------------------
    # 6. objective
    # ---------------------------------------------------------------------
    terms: list = []

    zone_index = _zone_deficits(active, zone_coverage, config)

    for (did, aid), var in x.items():
        d = by_id[did]
        travel_min = cm.get(aid, did) / 60.0
        val = _served_value(d, config, weights) * _equity_multiplier(d, zone_index, config)
        net = val - weights.time * travel_min
        terms.append(var * int(round(SCALE * net)))

    for (did, _aid), var in y.items():
        d = by_id[did]
        # Worth of resolving this demand's uncertainty: what we would gain by
        # knowing, scaled by how unsure we currently are.
        potential = demand_unit_value(d, weights) * d.need.people_upper
        doubt = (1.0 - d.quantity_confidence) if config.use_confidence else 0.5
        if config.use_trust:
            doubt = max(doubt, 1.0 - d.trust_score)
        val = weights.verification * potential * doubt
        terms.append(var * int(round(SCALE * val)))

    m.Maximize(sum(terms))

    # ---------------------------------------------------------------------
    # 7. solve
    # ---------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = config.time_limit_s
    solver.parameters.num_search_workers = config.workers
    status = solver.Solve(m)
    plan.solver_status = solver.StatusName(status)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        plan.objective_value = solver.ObjectiveValue() / SCALE
        _extract(plan, solver, x, y, by_id, assets, cm, config, weights, zone_index)

    served = {a.demand_id for a in plan.assignments}
    plan.unserved = [
        explain_unserved(d, cm, assets, reserve_n=reserve_n, config=config)
        for d in active
        if d.demand_id not in served
    ]
    plan.solve_time_ms = (time.perf_counter() - t0) * 1000.0
    return plan


# --------------------------------------------------------------------------
# candidate window
# --------------------------------------------------------------------------


def _candidate_window(active, cm: CostMatrix, config: SolverConfig, weights: Weights):
    """Rank demands cheaply and keep the top slice for the model.

    The ranking is the same shape as the objective - value over travel - so the
    window rarely excludes something that would have won. Ties break on demand
    id so the window is stable across replans and an operator does not watch
    rows shuffle for no reason.
    """
    if len(active) <= config.max_candidate_demands:
        return active

    scored = []
    for d in active:
        _, secs = cm.nearest_asset(d.demand_id)
        if secs is None:
            continue
        value = demand_unit_value(d, weights) * max(1, _value_headcount(d, config))
        if config.use_trust:
            value *= d.trust_score
        if config.use_escalation:
            value *= d.escalation_weight
        scored.append((-value / (1.0 + secs / 1800.0), d.demand_id, d))

    scored.sort(key=lambda r: (r[0], r[1]))
    return [d for _, _, d in scored[: config.max_candidate_demands]]


# --------------------------------------------------------------------------
# the two lines that are the whole confidence idea
# --------------------------------------------------------------------------


def _capacity_load(d, config: SolverConfig) -> int:
    """Seats to reserve. Upper bound: never turn up with too few."""
    return d.need.people_upper if config.use_confidence else d.need.people


def _value_headcount(d, config: SolverConfig) -> int:
    """People to take credit for. Lower bound: never over-credit a guess."""
    return d.need.people_lower if config.use_confidence else d.need.people


def _served_value(d, config: SolverConfig, w: Weights) -> float:
    v = demand_unit_value(d, w) * _value_headcount(d, config)
    if config.use_trust:
        v *= d.trust_score
    if config.use_escalation:
        v *= d.escalation_weight
    return v


def _serves(asset, demand) -> bool:
    return not asset.serves or demand.need.type.value in asset.serves


def _equity_zone(d, config: SolverConfig) -> str:
    """The zone this demand counts toward for the equity term.

    Coarsened from the demand's own hex to its ancestor at
    `equity_resolution`, so the maximin has tens of constraints rather than
    hundreds.
    """
    cell = d.location.h3_cell
    if not cell:
        return "unzoned"
    try:
        return h3.cell_to_parent(cell, config.equity_resolution)
    except Exception:
        return cell


def _needs_verification(d, config: SolverConfig) -> bool:
    return d.quantity_confidence < config.verify_threshold or d.trust_score < config.trust_threshold


# --------------------------------------------------------------------------
# equity as a per-zone deficit multiplier
# --------------------------------------------------------------------------
#
# This started as a textbook maximin: one variable for the worst-served zone's
# coverage fraction, one constraint per zone, maximise the minimum. It is the
# correct formulation and it did not survive measurement.
#
# Maximin couples every zone through a single variable, so CP-SAT has to reason
# about all of them at once to prove a bound. It cost 8 of the 10 seconds a
# replan was allowed - and it moved the worst-off-zone metric by nothing at
# all, because with several hundred zones carrying demand and a few hundred
# sorties available, the worst decile is empty no matter what the solver does.
# Eight seconds for zero measured effect is not a trade worth defending on
# stage.
#
# What replaced it is a value multiplier: a demand in a zone that has been
# served less gets weighted up, in proportion to the operator's equity setting.
# It is linear, costs nothing, uses coverage actually delivered so far rather
# than only this round's plan, and it appears in the justification trace as a
# number the operator can read.


def _zone_deficits(active, zone_coverage, config: SolverConfig) -> dict[str, float]:
    """How far behind each zone is, in [0, 1]. 1.0 means nothing yet."""
    if not config.use_equity or config.equity_weight <= 0.0:
        return {}
    covered = zone_coverage or {}
    out: dict[str, float] = {}
    for d in active:
        z = _equity_zone(d, config)
        if z not in out:
            out[z] = max(0.0, 1.0 - float(covered.get(z, 0.0)))
    return out


def _equity_multiplier(d, zone_index: dict[str, float], config: SolverConfig) -> float:
    """Weight-up factor for a demand in an under-served zone.

    At equity_weight 0 every zone is worth the same and the solver maximises
    throughput. At 1.0 a zone with nothing delivered is worth twice a zone
    already covered, which is enough to pull assets across a district without
    abandoning the urgent cases the objective is otherwise ranking.
    """
    if not zone_index:
        return 1.0
    deficit = zone_index.get(_equity_zone(d, config), 1.0)
    return 1.0 + config.equity_weight * deficit


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------


def _extract(plan, solver, x, y, by_id, assets, cm, config, weights, zone_index) -> None:
    asset_by_id = {a.asset_id: a for a in assets}

    for (did, aid), var in x.items():
        if not solver.Value(var):
            continue
        d, a = by_id[did], asset_by_id[aid]
        travel_min = cm.get(aid, did) / 60.0
        plan.assignments.append(
            Assignment(
                assignment_id=f"AS-{uuid.uuid4().hex[:8]}",
                asset_id=aid,
                demand_id=did,
                kind=TaskKind.RESCUE,
                zone=d.location.h3_cell,
                travel_minutes=round(travel_min, 1),
                people_committed=_capacity_load(d, config),
                objective_value=round(_served_value(d, config, weights) - weights.time * travel_min, 2),
                reasons=justify_assignment(d, a, cm, config, weights, zone_index),
                route=cm.route(aid, did, a.type),
            )
        )

    for (did, aid), var in y.items():
        if not solver.Value(var):
            continue
        d, a = by_id[did], asset_by_id[aid]
        plan.assignments.append(
            Assignment(
                assignment_id=f"AS-{uuid.uuid4().hex[:8]}",
                asset_id=aid,
                demand_id=did,
                kind=TaskKind.VERIFICATION,
                zone=d.location.h3_cell,
                travel_minutes=round(cm.get(aid, did) / 60.0, 1),
                people_committed=0,
                reasons=justify_assignment(
                    d, a, cm, config, weights, zone_index, kind=TaskKind.VERIFICATION
                ),
            )
        )
