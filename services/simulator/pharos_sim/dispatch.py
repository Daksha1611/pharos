"""Rolling dispatch simulation.

A single solve over a six-hour scenario would be a planning exercise, not a
dispatch system. Real operations replan on a tick: new reports arrive, assets
come free, roads fail, and the ordering changes as a result. That last point
is the whole thesis - priority is a property of a demand relative to the
capacity currently available to serve it, so it has to be recomputed as
capacity changes.

Each tick:

  1. Assets that finished their sortie return to their depot and go idle.
  2. Scheduled road degradation is applied, and the route cache invalidated.
  3. Demand state is rebuilt as of `now`: only messages already received
     count, so trust decays and corroboration accrues on the clock.
  4. Unresolved demands age, and their escalation weight rises. Nothing
     silently ages out.
  5. The policy assigns idle assets to demands.
  6. Assignments become in-flight jobs; outcomes are recorded on arrival.

Three policies share this loop, so the comparison is like for like: the
baselines are not handicapped by a different simulator.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pharos_allocator import graph as roads
from pharos_allocator.costmatrix import RouteOracle
from pharos_allocator.objective import SolverConfig, Weights
from pharos_allocator.solver import solve as cpsat_solve
from pharos_core import Asset, AssetState, DemandRecord, DemandStatus, Plan, TaskKind
from pharos_sensing.triage.calibration import headcount_interval

from . import baselines, fleet
from .metrics import ServedRecord
from .spec import ScenarioSpec

# A lead nobody has re-confirmed in this long is stale when it is dispatched.
STALE_AFTER_MINUTES = 120.0

# How fast an unresolved demand's weight grows, per hour waiting.
ESCALATION_PER_HOUR = 0.35
MAX_ESCALATION = 3.0


@dataclass
class DispatchConfig:
    policy: str = "pharos"  # pharos | fifo | nearest
    solver: SolverConfig = field(default_factory=SolverConfig)
    weights: Weights = field(default_factory=Weights)
    replan_minutes: float | None = None
    enable_escalation: bool = True
    enable_degradation: bool = True
    top_k_assets: int = 10
    verbose: bool = False


@dataclass
class InFlight:
    arrive_min: float
    free_min: float
    asset_id: str
    demand_id: str
    truth_id: str | None
    kind: str
    people_committed: int
    dispatched_min: float
    zone: str | None          # the demand's own hex, for display
    equity_zone: str | None   # the coarser zone the equity term measures
    stale: bool


@dataclass
class DispatchResult:
    served: list[ServedRecord]
    plans: list[Plan]
    solve_ms: list[float]
    final_demands: list[DemandRecord]
    ticks: int
    degradation_events: list[tuple[float, str, int]] = field(default_factory=list)

    @property
    def solve_seconds_total(self) -> float:
        return round(sum(self.solve_ms) / 1000.0, 3)

    @property
    def solve_ms_p95(self) -> float:
        if not self.solve_ms:
            return 0.0
        s = sorted(self.solve_ms)
        return round(s[min(len(s) - 1, int(len(s) * 0.95))], 1)


def run(
    sensing,
    truth_index: dict,
    spec: ScenarioSpec,
    rg: roads.RoadGraph,
    assets: list[Asset],
    t0: datetime,
    config: DispatchConfig | None = None,
) -> DispatchResult:
    cfg = config or DispatchConfig()
    tick = cfg.replan_minutes or spec.replan_minutes
    horizon = spec.duration_hours * 60.0

    oracle = RouteOracle(rg)
    assets = [a.model_copy(deep=True) for a in assets]
    by_asset = {a.asset_id: a for a in assets}
    depot_of = {a.asset_id: (a.lat, a.lon) for a in assets}

    free_at: dict[str, float] = {a.asset_id: 0.0 for a in assets}
    in_flight: list[InFlight] = []
    served: list[ServedRecord] = []
    plans: list[Plan] = []
    solve_ms: list[float] = []
    events: list[tuple[float, str, int]] = []

    resolved_demands: set[str] = set()
    committed_demands: set[str] = set()
    # People delivered and people demanded per equity zone, so the objective's
    # equity term reflects what has actually been delivered rather than only
    # what this round's plan proposes.
    zone_served: dict[str, float] = defaultdict(float)
    zone_demanded: dict[str, float] = defaultdict(float)
    verified_demands: set[str] = set()
    served_truths: set[str] = set()
    pending_degradation = sorted(spec.road_degradation, key=lambda d: d.at_hour)

    t = 0.0
    ticks = 0

    while t <= horizon + 1e-6:
        ticks += 1

        # -- 1. completions -------------------------------------------------
        still: list[InFlight] = []
        for job in in_flight:
            if job.arrive_min > t:
                still.append(job)
                continue
            rec = _record(job, truth_index, served_truths)
            served.append(rec)
            if rec.kind == TaskKind.RESCUE.value and not rec.is_duplicate_visit:
                zone_served[job.equity_zone or "unzoned"] += min(
                    rec.people_committed, rec.people_actually_present
                )
            if job.kind == TaskKind.VERIFICATION.value:
                verified_demands.add(job.demand_id)
            else:
                resolved_demands.add(job.demand_id)
            committed_demands.discard(job.demand_id)
        in_flight = still

        for a in assets:
            if free_at[a.asset_id] <= t:
                a.state = AssetState.IDLE
                a.lat, a.lon = depot_of[a.asset_id]

        # -- 2. road degradation --------------------------------------------
        if cfg.enable_degradation:
            while pending_degradation and pending_degradation[0].at_hour * 60.0 <= t:
                ev = pending_degradation.pop(0)
                edges = roads.pick_degradable_edges(
                    rg, ev.disable_fraction, seed=spec.seed + int(ev.at_hour * 10)
                )
                if ev.mode == "collapse":
                    roads.disable_edges(rg, edges)
                else:
                    roads.flood_edges(rg, edges)
                oracle.bump_road_version()
                events.append((t, ev.mode, len(edges)))

        # -- 3. demand state as of now --------------------------------------
        now = t0 + timedelta(minutes=t)
        demands = sensing.snapshot(now)

        active: list[DemandRecord] = []
        for d in demands:
            if d.demand_id in resolved_demands:
                d.status = DemandStatus.RESOLVED
                continue
            if d.demand_id in committed_demands:
                d.status = DemandStatus.ASSIGNED
                continue
            if d.demand_id in verified_demands:
                # Verification came back. The demand is corroborated, so it can
                # now compete for a physical asset on better evidence.
                d.quantity_confidence = min(0.95, d.quantity_confidence + 0.30)
                d.trust_score = min(1.0, d.trust_score + 0.25)
                lo, point, hi = headcount_interval(d.need.people, d.quantity_confidence)
                d.need.people_lower, d.need.people, d.need.people_upper = lo, point, hi
            # -- 4. escalation ----------------------------------------------
            if cfg.enable_escalation:
                waited_h = d.age_minutes(now) / 60.0
                d.escalation_weight = min(MAX_ESCALATION, 1.0 + ESCALATION_PER_HOUR * waited_h)
            active.append(d)

        idle = [a for a in assets if a.state == AssetState.IDLE]

        # -- 5. assign ------------------------------------------------------
        if active and idle:
            cm = oracle.build(idle, active, top_k=cfg.top_k_assets)
            t_solve = time.perf_counter()
            if cfg.policy == "pharos":
                # Coverage delivered so far, per equity zone. The equity term
                # reads this rather than only the current round's plan, so a
                # zone that has been quietly skipped for two hours keeps
                # climbing until something goes there.
                zone_demanded.clear()
                for d in active:
                    zone_demanded[_zone_of(d, cfg.solver)] += d.need.people
                coverage = {
                    z: min(1.0, zone_served.get(z, 0.0) / n)
                    for z, n in zone_demanded.items()
                    if n > 0
                }
                plan = cpsat_solve(
                    active, idle, cm, cfg.solver, cfg.weights, now=now, zone_coverage=coverage
                )
            elif cfg.policy == "fifo":
                plan = baselines.fifo_assign(active, idle, cm, now=now)
            elif cfg.policy == "nearest":
                plan = baselines.nearest_asset_assign(active, idle, cm, now=now)
            else:
                raise ValueError(f"unknown policy {cfg.policy!r}")
            solve_ms.append((time.perf_counter() - t_solve) * 1000.0)
            plans.append(plan)

            # -- 6. dispatch ---------------------------------------------------
            by_demand = {d.demand_id: d for d in active}
            for asn in plan.assignments:
                a = by_asset[asn.asset_id]
                d = by_demand.get(asn.demand_id)
                if d is None or a.state != AssetState.IDLE:
                    continue
                travel = asn.travel_minutes
                service = fleet.service_minutes(a, asn.people_committed)
                arrive = t + travel
                # Round trip: an asset that took people out has to come back
                # before it can go again. Skipping the return leg would
                # roughly double every fleet's effective capacity.
                free = arrive + service + (0.0 if a.is_verifier else travel)

                a.state = AssetState.EN_ROUTE
                free_at[a.asset_id] = free
                committed_demands.add(d.demand_id)
                in_flight.append(
                    InFlight(
                        arrive_min=arrive,
                        free_min=free,
                        asset_id=a.asset_id,
                        demand_id=d.demand_id,
                        truth_id=d.truth_id,
                        kind=asn.kind.value,
                        people_committed=asn.people_committed,
                        dispatched_min=t,
                        zone=asn.zone,
                        equity_zone=_zone_of(d, cfg.solver),
                        stale=d.staleness_minutes(now) > STALE_AFTER_MINUTES,
                    )
                )

        if cfg.verbose:
            print(
                f"  t={t:6.0f}m  active={len(active):5}  idle={len(idle):3}  "
                f"inflight={len(in_flight):3}  served={len(served):5}"
            )
        t += tick

    # Drain anything still in the air at the horizon.
    for job in sorted(in_flight, key=lambda j: j.arrive_min):
        served.append(_record(job, truth_index, served_truths))

    return DispatchResult(
        served=served,
        plans=plans,
        solve_ms=solve_ms,
        final_demands=sensing.snapshot(t0 + timedelta(minutes=horizon)),
        ticks=ticks,
        degradation_events=events,
    )


def _zone_of(d, solver_config) -> str:
    from pharos_allocator.solver import _equity_zone

    return _equity_zone(d, solver_config)


def _record(job: InFlight, truth_index: dict, served_truths: set[str]) -> ServedRecord:
    """What the asset actually found when it got there."""
    t = truth_index.get(job.truth_id or "")
    is_hoax = bool(t and t.is_hoax)

    # A second sortie to an event already served is wasted, whatever the plan
    # believed. This is how duplicate demand records turn into duplicate boats.
    duplicate = False
    if t is not None and job.kind == TaskKind.RESCUE.value:
        duplicate = t.truth_id in served_truths
        served_truths.add(t.truth_id)

    present = 0 if (t is None or is_hoax) else t.people

    return ServedRecord(
        demand_id=job.demand_id,
        truth_id=job.truth_id,
        asset_id=job.asset_id,
        asset_type=job.asset_id.split("-")[0],
        kind=job.kind,
        zone=job.zone,
        dispatched_at_min=job.dispatched_min,
        arrived_at_min=job.arrive_min,
        people_committed=job.people_committed,
        people_actually_present=present,
        is_hoax=is_hoax,
        is_stale=job.stale,
        is_duplicate_visit=duplicate,
    )
