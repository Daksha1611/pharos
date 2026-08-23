"""The live demo session.

Holds one scenario mid-flight: the road network, the sensing output, the fleet,
the clock, and the current plan. The console drives it - advance the clock,
move the equity control, break a bridge, inject a hoax - and every action
re-solves and pushes the result.

Everything runs in this process against SQLite and an in-memory queue. That is
deliberate: the demo must survive a venue with no wifi and a laptop with no
containers running. The Postgres, PostGIS and Redis Streams path is wired the
same way behind `PHAROS_DATABASE_URL` and `PHAROS_QUEUE_BACKEND` for the
scaled deployment.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pharos_allocator import graph as roads
from pharos_allocator.costmatrix import RouteOracle
from pharos_allocator.objective import SolverConfig, Weights
from pharos_allocator.solver import solve
from pharos_allocator.zones import assign_cells
from pharos_core import Asset, AssetState, DemandRecord, DemandStatus, Plan, TaskKind
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sensing.triage.calibration import headcount_interval
from pharos_sim import fleet, generator, redteam, spec
from pharos_sim.dispatch import ESCALATION_PER_HOUR, MAX_ESCALATION, STALE_AFTER_MINUTES

from .audit import AuditLog


@dataclass
class InFlightJob:
    asset_id: str
    demand_id: str
    kind: str
    dispatched_min: float
    arrive_min: float
    free_min: float
    people_committed: int
    route: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class SessionStatus:
    phase: str = "idle"  # idle | loading | ready | error
    detail: str = ""
    progress: float = 0.0


class Session:
    """One scenario, live. Not thread-safe by design - guarded by `lock`."""

    def __init__(self, scenario_path: str, tick_minutes: float = 15.0):
        self.scenario_path = scenario_path
        self.tick_minutes = tick_minutes
        self.lock = threading.RLock()
        self.status = SessionStatus()
        self.audit = AuditLog()

        self.spec = None
        self.data = None
        self.sensing = None
        self.rg = None
        self.oracle = None
        self.assets: list[Asset] = []
        self.depots = []

        self.clock_min = 0.0
        self.plan: Plan | None = None
        self.solver = SolverConfig()
        self.weights = Weights()

        self.in_flight: list[InFlightJob] = []
        self.free_at: dict[str, float] = {}
        self.depot_of: dict[str, tuple[float, float]] = {}
        self.resolved: set[str] = set()
        self.committed: set[str] = set()
        self.verified: set[str] = set()

        self.events: list[dict] = []
        self.pending_degradation = []
        self._demand_cache: list[DemandRecord] = []
        self._cache_at: float = -1.0
        self.confidence_override: float | None = None
        self.solve_ms_history: list[float] = []

    # ------------------------------------------------------------------
    # bring-up
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Generate the scenario and run sensing. Slow; call off the request thread."""
        try:
            self.status = SessionStatus("loading", "generating scenario", 0.05)
            s = spec.load(self.scenario_path)
            self.spec = s
            self.tick_minutes = s.replan_minutes
            self.data = generator.generate(s)

            self.status = SessionStatus("loading", "building road network", 0.25)
            self.rg = roads.load_or_build(
                "data/road_graph.pkl", s.region.centre, s.region.radius_km, seed=s.seed
            )
            roads.restore(self.rg)
            self.oracle = RouteOracle(self.rg)
            self.assets, self.depots = fleet.build(s, self.rg)
            self.free_at = {a.asset_id: 0.0 for a in self.assets}
            self.depot_of = {a.asset_id: (a.lat, a.lon) for a in self.assets}

            self.status = SessionStatus(
                "loading", f"sensing {len(self.data.messages):,} messages", 0.45
            )
            pipeline = SensingPipeline(
                self.data.gazetteer, s.region.centre, SensingConfig()
            )
            t = time.perf_counter()
            self.sensing = pipeline.process(
                list(self.data.messages),
                now=self.data.t0 + timedelta(hours=s.duration_hours),
                t0=self.data.t0,
            )
            self.sensing_seconds = time.perf_counter() - t
            _attach_truth(self.sensing, self.data)
            assign_cells(self.sensing.demands, s.region.h3_resolution)

            self.pending_degradation = sorted(s.road_degradation, key=lambda d: d.at_hour)
            self.status = SessionStatus("loading", "first plan", 0.9)
            self.replan(reason="session start")
            self.status = SessionStatus("ready", "", 1.0)
        except Exception as exc:  # surfaced to the console rather than swallowed
            self.status = SessionStatus("error", f"{type(exc).__name__}: {exc}", 0.0)
            raise

    @property
    def ready(self) -> bool:
        return self.status.phase == "ready"

    @property
    def now(self) -> datetime:
        return self.data.t0 + timedelta(minutes=self.clock_min)

    @property
    def horizon_min(self) -> float:
        return self.spec.duration_hours * 60.0

    # ------------------------------------------------------------------
    # the clock
    # ------------------------------------------------------------------

    def tick(self, minutes: float | None = None) -> Plan:
        """Advance the scenario one replan step."""
        with self.lock:
            step = minutes if minutes is not None else self.tick_minutes
            self.clock_min = min(self.horizon_min, self.clock_min + step)
            self._complete_arrivals()
            self._apply_scheduled_degradation()
            return self.replan(reason=f"clock advanced to +{self.clock_min:.0f}m")

    def _complete_arrivals(self) -> None:
        still = []
        for job in self.in_flight:
            if job.arrive_min > self.clock_min:
                still.append(job)
                continue
            if job.kind == TaskKind.VERIFICATION.value:
                self.verified.add(job.demand_id)
            else:
                self.resolved.add(job.demand_id)
            self.committed.discard(job.demand_id)
        self.in_flight = still

        for a in self.assets:
            if self.free_at[a.asset_id] <= self.clock_min:
                a.state = AssetState.IDLE
                a.lat, a.lon = self.depot_of[a.asset_id]
            elif any(j.asset_id == a.asset_id and j.arrive_min <= self.clock_min
                     for j in self.in_flight):
                a.state = AssetState.ON_SITE

    def _apply_scheduled_degradation(self) -> None:
        while self.pending_degradation and self.pending_degradation[0].at_hour * 60.0 <= self.clock_min:
            ev = self.pending_degradation.pop(0)
            edges = roads.pick_degradable_edges(
                self.rg, ev.disable_fraction, seed=self.spec.seed + int(ev.at_hour * 10)
            )
            roads.flood_edges(self.rg, edges)
            self.oracle.bump_road_version()
            self._event("road_degraded", f"{len(edges)} segments flooded", {"edges": len(edges)})

    # ------------------------------------------------------------------
    # demand state
    # ------------------------------------------------------------------

    def demands(self, refresh: bool = False) -> list[DemandRecord]:
        if not refresh and self._cache_at == self.clock_min and self._demand_cache:
            return self._demand_cache

        out = []
        for d in self.sensing.snapshot(self.now):
            if d.demand_id in self.resolved:
                d.status = DemandStatus.RESOLVED
            elif d.demand_id in self.committed:
                d.status = DemandStatus.ASSIGNED
            elif d.demand_id in self.verified:
                # A verification task came back. That is exactly what it was
                # dispatched to do: narrow the interval. Raising confidence
                # without narrowing the range would leave the panel claiming
                # 0.95 certainty next to a spread of a hundred people.
                d.status = DemandStatus.VERIFYING
                d.quantity_confidence = min(0.95, d.quantity_confidence + 0.30)
                d.trust_score = min(1.0, d.trust_score + 0.25)
                lo, point, hi = headcount_interval(d.need.people, d.quantity_confidence)
                d.need.people_lower, d.need.people, d.need.people_upper = lo, point, hi

            if self.confidence_override is not None:
                # Demo control: force the sensing layer's confidence down so the
                # graceful-degradation path can be shown on stage.
                d.quantity_confidence = min(d.quantity_confidence, self.confidence_override)

            waited_h = d.age_minutes(self.now) / 60.0
            d.escalation_weight = min(MAX_ESCALATION, 1.0 + ESCALATION_PER_HOUR * waited_h)
            out.append(d)

        self._demand_cache = out
        self._cache_at = self.clock_min
        return out

    def active_demands(self) -> list[DemandRecord]:
        return [
            d
            for d in self.demands()
            if d.status in (DemandStatus.UNASSIGNED, DemandStatus.VERIFYING)
        ]

    def idle_assets(self) -> list[Asset]:
        return [a for a in self.assets if a.state == AssetState.IDLE]

    # ------------------------------------------------------------------
    # solving
    # ------------------------------------------------------------------

    def _release_pending(self) -> int:
        """Un-dispatch anything committed at the current tick but not yet arrived.

        Re-deciding is not the same as deciding again. When the operator moves
        the equity control, or a bridge fails, or a hoax lands, the right
        behaviour is to reconsider *this* moment - not to layer a second round
        of commitments on top of the first.

        Without this, dragging the equity slider twice dispatched twice: the
        first solve committed the fleet, the second had almost nothing left,
        and the plan appeared to collapse rather than rebalance. On stage that
        reads as the system falling over at the exact moment it is supposed to
        show its best trick.

        Only jobs dispatched at the current clock and still in transit are
        released. An asset that has already arrived has done the work, and a
        rescue that already happened is not recallable.
        """
        keep, released = [], 0
        for job in self.in_flight:
            recallable = job.dispatched_min >= self.clock_min and job.arrive_min > self.clock_min
            if not recallable:
                keep.append(job)
                continue
            asset = next((a for a in self.assets if a.asset_id == job.asset_id), None)
            if asset is not None:
                asset.state = AssetState.IDLE
                asset.lat, asset.lon = self.depot_of[job.asset_id]
                self.free_at[job.asset_id] = self.clock_min
            self.committed.discard(job.demand_id)
            released += 1
        self.in_flight = keep
        self._cache_at = -1.0
        return released

    def replan(self, reason: str = "") -> Plan:
        with self.lock:
            self._cache_at = -1.0
            active = self.active_demands()
            idle = self.idle_assets()
            if not active or not idle:
                self.plan = Plan(plan_id="PLAN-empty", created_at=self.now, solver_status="EMPTY")
                return self.plan

            cm = self.oracle.build(idle, active, top_k=self.solver.top_k_assets)
            t = time.perf_counter()
            plan = solve(active, idle, cm, self.solver, self.weights, now=self.now)
            self.solve_ms_history.append((time.perf_counter() - t) * 1000.0)

            self._dispatch(plan, cm)
            self.plan = plan
            self.audit.record(
                actor="system",
                action="replan",
                entity_type="plan",
                entity_id=plan.plan_id,
                evidence={
                    "reason": reason,
                    "clock_min": self.clock_min,
                    "active_demands": len(active),
                    "idle_assets": len(idle),
                    "assignments": len(plan.assignments),
                    "equity_weight": self.solver.equity_weight,
                    "mode": plan.mode.value,
                    "solver_status": plan.solver_status,
                },
            )
            return plan

    def _dispatch(self, plan: Plan, cm) -> None:
        by_asset = {a.asset_id: a for a in self.assets}
        by_demand = {d.demand_id: d for d in self.active_demands()}

        for asn in plan.assignments:
            a = by_asset.get(asn.asset_id)
            d = by_demand.get(asn.demand_id)
            if a is None or d is None or a.state != AssetState.IDLE:
                continue
            service = fleet.service_minutes(a, asn.people_committed)
            arrive = self.clock_min + asn.travel_minutes
            free = arrive + service + (0.0 if a.is_verifier else asn.travel_minutes)

            a.state = AssetState.EN_ROUTE
            self.free_at[a.asset_id] = free
            self.committed.add(d.demand_id)
            self.in_flight.append(
                InFlightJob(
                    asset_id=a.asset_id,
                    demand_id=d.demand_id,
                    kind=asn.kind.value,
                    dispatched_min=self.clock_min,
                    arrive_min=arrive,
                    free_min=free,
                    people_committed=asn.people_committed,
                    route=asn.route,
                )
            )

    # ------------------------------------------------------------------
    # operator and demo controls
    # ------------------------------------------------------------------

    def set_equity(self, weight: float, actor: str = "operator") -> Plan:
        with self.lock:
            old = self.solver.equity_weight
            self.solver.equity_weight = max(0.0, min(1.0, float(weight)))
            released = self._release_pending()
            self.audit.record(
                actor=actor,
                action="set_equity_weight",
                entity_type="policy",
                entity_id="equity",
                evidence={
                    "from": old,
                    "to": self.solver.equity_weight,
                    "assignments_recalled": released,
                },
            )
            return self.replan(reason=f"equity weight {old:.2f} -> {self.solver.equity_weight:.2f}")

    def set_confidence_floor(self, value: float | None, actor: str = "operator") -> Plan:
        """Force intake confidence down, to demonstrate graceful degradation."""
        with self.lock:
            self.confidence_override = value
            self._release_pending()
            self._event(
                "confidence_override",
                "intake confidence forced low" if value is not None else "confidence restored",
                {"cap": value},
            )
            self.audit.record(
                actor=actor,
                action="override_confidence",
                entity_type="policy",
                entity_id="confidence",
                evidence={"cap": value},
            )
            return self.replan(reason="confidence override")

    def break_bridge(self, actor: str = "operator") -> dict:
        """Collapse a river crossing. The chokepoint the network is built around."""
        with self.lock:
            standing = [
                (u, v)
                for u, v in self.rg.bridges
                if self.rg.G.has_edge(u, v) and not self.rg.G.edges[u, v].get("disabled")
            ]
            if not standing:
                return {"broken": None, "remaining": 0}
            edge = standing[0]
            roads.disable_edges(self.rg, [edge])
            self.oracle.bump_road_version()
            lat, lon = self.rg.node_latlon(edge[0])
            released = self._release_pending()
            self._event(
                "bridge_collapsed",
                f"river crossing lost; {released} in-transit task(s) reconsidered",
                {"lat": lat, "lon": lon, "recalled": released},
            )
            self.audit.record(
                actor=actor,
                action="bridge_collapsed",
                entity_type="road",
                entity_id=self.rg.G.edges[edge[0], edge[1]]["edge_id"],
                evidence={"lat": lat, "lon": lon},
            )
            self.replan(reason="bridge collapsed")
            return {"broken": {"lat": lat, "lon": lon}, "remaining": len(standing) - 1}

    def inject_hoax(self, kind: str = "hoax_cluster", actor: str = "operator") -> dict:
        """Red team. Injects fabricated traffic into the live intake."""
        with self.lock:
            added = redteam.inject(self.sensing, self.data, self.spec, self.now, kind)
            self._release_pending()
            self._event("redteam", f"{kind}: {added['messages']} messages injected", added)
            self.audit.record(
                actor=actor,
                action="redteam_injection",
                entity_type="intake",
                entity_id=kind,
                evidence=added,
            )
            self.replan(reason=f"red team: {kind}")
            return added

    def override_assignment(
        self, demand_id: str, asset_id: str, reason: str, actor: str = "operator"
    ) -> Plan:
        """Manual reassignment. Always allowed, always logged, always re-solved
        around - an automated decision an operator cannot override is not
        decision support."""
        with self.lock:
            self.audit.record(
                actor=actor,
                action="manual_override",
                entity_type="assignment",
                entity_id=demand_id,
                evidence={"asset_id": asset_id, "reason": reason},
            )
            a = next((x for x in self.assets if x.asset_id == asset_id), None)
            d = next((x for x in self.demands() if x.demand_id == demand_id), None)
            if a is None or d is None:
                return self.plan
            cm = self.oracle.build([a], [d], top_k=1)
            secs = cm.get(asset_id, demand_id)
            if secs is None:
                return self.plan
            travel = secs / 60.0
            service = fleet.service_minutes(a, d.need.people_upper)
            a.state = AssetState.EN_ROUTE
            arrive = self.clock_min + travel
            self.free_at[asset_id] = arrive + service + travel
            self.committed.add(demand_id)
            self.in_flight.append(
                InFlightJob(
                    asset_id=asset_id,
                    demand_id=demand_id,
                    kind=TaskKind.RESCUE.value,
                    dispatched_min=self.clock_min,
                    arrive_min=arrive,
                    free_min=arrive + service + travel,
                    people_committed=d.need.people_upper,
                    route=cm.route(asset_id, demand_id, a.type),
                )
            )
            return self.replan(reason="manual override")

    def reset(self) -> None:
        with self.lock:
            self.clock_min = 0.0
            self.in_flight.clear()
            self.resolved.clear()
            self.committed.clear()
            self.verified.clear()
            self.events.clear()
            self.confidence_override = None
            self.solve_ms_history.clear()
            roads.restore(self.rg)
            self.oracle.bump_road_version()
            for a in self.assets:
                a.state = AssetState.IDLE
                a.lat, a.lon = self.depot_of[a.asset_id]
                self.free_at[a.asset_id] = 0.0
            self.pending_degradation = sorted(
                self.spec.road_degradation, key=lambda d: d.at_hour
            )
            self._cache_at = -1.0
            self.replan(reason="reset")

    # ------------------------------------------------------------------

    def _event(self, kind: str, message: str, payload: dict | None = None) -> None:
        self.events.append(
            {
                "at_min": round(self.clock_min, 1),
                "kind": kind,
                "message": message,
                "payload": payload or {},
            }
        )

    def stale_demands(self) -> list[DemandRecord]:
        return [
            d
            for d in self.demands()
            if d.staleness_minutes(self.now) > STALE_AFTER_MINUTES
            and d.status == DemandStatus.UNASSIGNED
        ]


def _attach_truth(sensing, data) -> None:
    """Evaluation wiring only - the console shows it as 'ground truth' in the
    metrics panel and nothing in the decision path reads it."""
    from collections import Counter

    mmap = data.message_truth_map()
    for demand in sensing.demands:
        votes = Counter(mmap[m] for m in demand.source_message_ids if m in mmap)
        demand.truth_id = votes.most_common(1)[0][0] if votes else None
