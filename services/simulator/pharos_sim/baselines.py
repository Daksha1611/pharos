"""The two dumb-but-sensible allocation policies.

These are the "compared to what?" answer, and they are worth twenty minutes of
work each. A team that cannot say what its optimizer beats has not measured
anything.

Both emit a `Plan` with the same shape the solver produces, and both run
inside the same dispatch loop against the same cost matrix, so the comparison
is like for like rather than a rigged race.

Neither baseline reads confidence, trust, resolution level or zone coverage.
That is the point: they are what a system without the seam can do.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pharos_core import Assignment, Plan, Reason, TaskKind


def fifo_assign(demands, assets, cm, now: datetime | None = None) -> Plan:
    """First come, first served.

    The policy a control room falls back to when the queue is a list of
    timestamps, which is what an ordinary ticketing system gives you.
    """
    plan = Plan(
        plan_id=f"FIFO-{uuid.uuid4().hex[:8]}",
        created_at=now or datetime.now(),
        solver_status="BASELINE_FIFO",
    )
    capacity = {a.asset_id: a.capacity for a in assets}
    available = {a.asset_id: a for a in assets if not a.is_verifier}

    for d in sorted(demands, key=lambda x: x.first_reported_at):
        best = _cheapest_reachable(d, available, capacity, cm)
        if best is None:
            continue
        aid, travel_s = best
        _commit(plan, d, available[aid], travel_s, capacity, cm, "oldest report first")
    return plan


def nearest_asset_assign(demands, assets, cm, now: datetime | None = None) -> Plan:
    """Greedy by distance: every asset takes the closest thing it can serve.

    The obvious policy, and a genuinely decent one - it beats FIFO on time to
    reach. It also concentrates effort wherever assets happen to be staged,
    which is exactly the equity failure the objective's maximin term exists to
    correct.
    """
    plan = Plan(
        plan_id=f"NEAR-{uuid.uuid4().hex[:8]}",
        created_at=now or datetime.now(),
        solver_status="BASELINE_NEAREST",
    )
    capacity = {a.asset_id: a.capacity for a in assets}
    taken: set[str] = set()

    pairs = []
    for a in assets:
        if a.is_verifier:
            continue
        for d in demands:
            t = cm.get(a.asset_id, d.demand_id)
            if t is not None and _serves(a, d):
                pairs.append((t, a.asset_id, d.demand_id))
    pairs.sort()

    by_asset = {a.asset_id: a for a in assets}
    by_demand = {d.demand_id: d for d in demands}

    for travel_s, aid, did in pairs:
        if did in taken:
            continue
        d = by_demand[did]
        if capacity[aid] < d.need.people:
            continue
        taken.add(did)
        _commit(plan, d, by_asset[aid], travel_s, capacity, cm, "nearest available asset")
    return plan


# --------------------------------------------------------------------------


def _serves(asset, demand) -> bool:
    return not asset.serves or demand.need.type.value in asset.serves


def _cheapest_reachable(d, available, capacity, cm):
    best = None
    for aid, a in available.items():
        if not _serves(a, d) or capacity[aid] < d.need.people:
            continue
        t = cm.get(aid, d.demand_id)
        if t is not None and (best is None or t < best[1]):
            best = (aid, t)
    return best


def _commit(plan, d, asset, travel_s, capacity, cm, rationale: str) -> None:
    # Baselines have no interval to reason about, so they commit against the
    # point estimate - which is exactly how a plan ends up under-provisioned
    # when the extraction was uncertain.
    people = d.need.people
    capacity[asset.asset_id] -= people
    plan.assignments.append(
        Assignment(
            assignment_id=f"AS-{uuid.uuid4().hex[:8]}",
            asset_id=asset.asset_id,
            demand_id=d.demand_id,
            kind=TaskKind.RESCUE,
            zone=d.location.h3_cell,
            travel_minutes=round(travel_s / 60.0, 1),
            people_committed=people,
            reasons=[Reason(factor="policy", value=rationale)],
        )
    )
