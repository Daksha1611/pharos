"""Serialisers: session state as the console needs it.

Two rules run through all of this.

No model output is shown without its confidence attached. A demand's headcount
is always sent as an interval and a confidence, never as a bare number, because
the operator's decision is different when the system is guessing.

A location is never sent as a pin unless it was resolved as one. `render_as`
carries the honest answer - point, hex, or list-only - and the map obeys it.
That is the direct fix for the documented Kerala supply-drop failure.
"""

from __future__ import annotations

from collections import Counter

from pharos_allocator.zones import cell_boundary
from pharos_core import DemandStatus, GeoResolution, TaskKind
from pharos_sensing.dedupe.cluster import metres

# How the map is allowed to draw a demand, by how well we actually located it.
RENDER_BY_RESOLUTION = {
    GeoResolution.POINT: "pin",
    GeoResolution.BUILDING: "pin",
    GeoResolution.STREET: "circle",
    GeoResolution.WARD: "hex",
    GeoResolution.UNKNOWN: "list_only",
}


# --------------------------------------------------------------------------
# demands
# --------------------------------------------------------------------------


def demand_view(session, **f) -> dict:
    rows = session.demands()
    total_all = len(rows)

    rows = [d for d in rows if _matches(d, session, f)]
    rows.sort(key=lambda d: -_priority(d, session))

    offset, limit = f.get("offset", 0), f.get("limit", 300)
    page = rows[offset : offset + limit]

    return {
        "total": len(rows),
        "total_unfiltered": total_all,
        "offset": offset,
        "counts": _counts(session),
        "demands": [_demand_row(d, session) for d in page],
    }


def _matches(d, session, f) -> bool:
    if f.get("status") and d.status.value != f["status"]:
        return False
    if f.get("need") and d.need.type.value != f["need"]:
        return False
    if f.get("zone") and d.location.h3_cell != f["zone"]:
        return False
    if f.get("resolution") and d.location.resolution.value != f["resolution"]:
        return False
    if not (f.get("min_confidence", 0.0) <= d.quantity_confidence <= f.get("max_confidence", 1.0)):
        return False
    if d.trust_score < f.get("min_trust", 0.0):
        return False
    q = (f.get("search") or "").strip().lower()
    if q:
        hay = " ".join([d.demand_id, d.location.method, *d.raw_texts]).lower()
        if q not in hay:
            return False
    return True


def _priority(d, session) -> float:
    """The queue order. Deliberately the same shape as the objective, so the
    row an operator sees at the top is the one the solver is arguing for."""
    from pharos_allocator.objective import demand_unit_value

    v = demand_unit_value(d, session.weights) * d.need.people_lower
    v *= d.trust_score * d.escalation_weight
    if d.status is DemandStatus.ASSIGNED:
        v *= 0.35
    elif d.status is DemandStatus.RESOLVED:
        v *= 0.05
    return v


def _demand_row(d, session) -> dict:
    assignment = _assignment_for(session, d.demand_id)
    return {
        "demand_id": d.demand_id,
        "status": d.status.value,
        "need": d.need.type.value,
        "urgency": d.need.medical_urgency.value,
        "vulnerability": d.need.vulnerability_flags,
        # Never a bare number: the interval and its confidence travel together.
        "people": d.need.people,
        "people_lower": d.need.people_lower,
        "people_upper": d.need.people_upper,
        "quantity_confidence": d.quantity_confidence,
        "trust_score": d.trust_score,
        "duplicate_collapse_count": d.duplicate_collapse_count,
        "channels": d.channels,
        "escalation_weight": round(d.escalation_weight, 2),
        "time_decay": d.time_decay_class.value,
        "first_reported_at": d.first_reported_at.isoformat(),
        "last_corroborated_at": d.last_corroborated_at.isoformat(),
        "staleness_minutes": round(d.staleness_minutes(session.now), 1),
        "location": _location(d),
        "priority": round(_priority(d, session), 2),
        "assigned_asset": assignment.asset_id if assignment else None,
        "assignment_kind": assignment.kind.value if assignment else None,
        "preview": d.raw_texts[0][:160] if d.raw_texts else "",
    }


def _location(d) -> dict:
    return {
        "lat": d.location.lat,
        "lon": d.location.lon,
        "resolution": d.location.resolution.value,
        "geo_confidence": d.location.geo_confidence,
        "method": d.location.method,
        "h3_cell": d.location.h3_cell,
        # The map obeys this. A ward-level demand is a hex, never a pin.
        "render_as": RENDER_BY_RESOLUTION.get(d.location.resolution, "list_only"),
    }


def _counts(session) -> dict:
    rows = session.demands()
    return {
        "by_status": dict(Counter(d.status.value for d in rows)),
        "by_need": dict(Counter(d.need.type.value for d in rows)),
        "by_resolution": dict(Counter(d.location.resolution.value for d in rows)),
        "low_confidence": sum(1 for d in rows if d.quantity_confidence < 0.55),
        "low_trust": sum(1 for d in rows if d.trust_score < 0.40),
        "unlocatable": sum(
            1 for d in rows if d.location.resolution is GeoResolution.UNKNOWN
        ),
        "stale": len(session.stale_demands()),
    }


# --------------------------------------------------------------------------
# one demand, in full
# --------------------------------------------------------------------------


def demand_detail(session, demand_id: str) -> dict | None:
    d = next((x for x in session.demands() if x.demand_id == demand_id), None)
    if d is None:
        return None

    idx = {p.envelope.message_id: p for p in session.sensing.processed}
    sources = []
    for mid in d.source_message_ids:
        p = idx.get(mid)
        if p is None:
            continue
        sources.append(
            {
                "message_id": mid,
                "channel": p.envelope.channel.value,
                # The original is kept alongside the normalized text, because
                # the operator needs to see what the citizen actually wrote.
                "raw_text": p.envelope.raw_text,
                "normalized_text": p.envelope.normalized_text,
                "language": p.envelope.detected_language,
                "language_confidence": p.envelope.language_confidence,
                "received_at": p.envelope.received_at.isoformat(),
                "sender": p.envelope.sender_hash[:10],
                "had_coordinates": p.envelope.attached_geo is not None,
                "resolved_by": p.location.method,
                "resolution": p.location.resolution.value,
                "extracted": {
                    "need": p.extraction.need_type.value,
                    "people": p.extraction.people,
                    "people_method": p.extraction.people_method,
                    "urgency": p.extraction.medical_urgency.value,
                    "vulnerability": p.extraction.vulnerability_flags,
                },
            }
        )

    spread = 0.0
    pts = [
        (idx[m].location.lat, idx[m].location.lon)
        for m in d.source_message_ids
        if m in idx and idx[m].location.resolution is not GeoResolution.UNKNOWN
    ]
    if len(pts) > 1:
        spread = max(metres(*a, *b) for i, a in enumerate(pts) for b in pts[i + 1 :])

    assignment = _assignment_for(session, demand_id)
    return {
        **_demand_row(d, session),
        "field_confidence": {
            "need_type": d.field_confidence.need_type,
            "headcount": d.field_confidence.headcount,
            "vulnerability": d.field_confidence.vulnerability,
            "medical_urgency": d.field_confidence.medical_urgency,
        },
        "sources": sources,
        "cluster_spread_m": round(spread, 1),
        "needs_disambiguation": d.location.resolution is GeoResolution.UNKNOWN,
        "assignment": _assignment_row(assignment, session) if assignment else None,
        "unserved_reason": _unserved_reason(session, demand_id),
        "audit": [
            {"at": e.created_at, "actor": e.actor, "action": e.action, "evidence": e.evidence}
            for e in session.audit.for_entity("assignment", demand_id)[:10]
        ],
    }


def _unserved_reason(session, demand_id: str) -> str | None:
    if not session.plan:
        return None
    for u in session.plan.unserved:
        if u.demand_id == demand_id:
            return u.explanation
    return None


# --------------------------------------------------------------------------
# assets and plan
# --------------------------------------------------------------------------


def asset_view(session) -> dict:
    jobs = {j.asset_id: j for j in session.in_flight}
    out = []
    for a in session.assets:
        j = jobs.get(a.asset_id)
        out.append(
            {
                "asset_id": a.asset_id,
                "type": a.type.value,
                "capacity": a.capacity,
                "speed_kmh": a.speed_kmh,
                "state": a.state.value,
                "lat": a.lat,
                "lon": a.lon,
                "depot_id": a.depot_id,
                "is_verifier": a.is_verifier,
                "serves": a.serves,
                "job": None
                if j is None
                else {
                    "demand_id": j.demand_id,
                    "kind": j.kind,
                    "people_committed": j.people_committed,
                    "eta_minutes": round(max(0.0, j.arrive_min - session.clock_min), 1),
                    "free_in_minutes": round(max(0.0, j.free_min - session.clock_min), 1),
                },
            }
        )
    return {
        "assets": out,
        "depots": [
            {"depot_id": d.depot_id, "name": d.name, "lat": d.lat, "lon": d.lon}
            for d in session.depots
        ],
        "counts": dict(Counter(a.state.value for a in session.assets)),
    }


def plan_view(session) -> dict:
    p = session.plan
    if p is None:
        return {"plan_id": None, "assignments": [], "unserved": []}
    return {
        "plan_id": p.plan_id,
        "created_at": p.created_at.isoformat(),
        "mode": p.mode.value,
        "banner": p.banner,
        "equity_weight": p.equity_weight,
        "solver_status": p.solver_status,
        "solve_time_ms": round(p.solve_time_ms, 1),
        "objective_value": round(p.objective_value, 2),
        "reserve": None
        if p.reserve is None
        else {
            "assets_held": p.reserve.assets_held,
            "total_assets": p.reserve.total_assets,
            "mean_confidence": p.reserve.mean_confidence,
            "rationale": p.reserve.rationale,
        },
        "assignments": [_assignment_row(a, session) for a in p.assignments],
        "counts": {
            "rescue": len(p.rescue_assignments),
            "verification": len(p.verification_assignments),
            "unserved": len(p.unserved),
        },
        "unserved": [
            {
                "demand_id": u.demand_id,
                "explanation": u.explanation,
                "nearest_asset_id": u.nearest_asset_id,
                "nearest_travel_minutes": u.nearest_travel_minutes,
            }
            for u in p.unserved[:40]
        ],
    }


def _assignment_row(a, session) -> dict:
    return {
        "assignment_id": a.assignment_id,
        "asset_id": a.asset_id,
        "demand_id": a.demand_id,
        "kind": a.kind.value,
        "zone": a.zone,
        "travel_minutes": a.travel_minutes,
        "people_committed": a.people_committed,
        "objective_value": a.objective_value,
        "route": [[lat, lon] for lat, lon in a.route],
        "reasons": [
            {"factor": r.factor, "value": r.value, "contribution": r.contribution}
            for r in a.reasons
        ],
    }


def _assignment_for(session, demand_id: str):
    if not session.plan:
        return None
    return next((a for a in session.plan.assignments if a.demand_id == demand_id), None)


# --------------------------------------------------------------------------
# map layers
# --------------------------------------------------------------------------


def road_view(session, bbox: str | None = None) -> dict:
    """Road segments, split by state so the map can colour them.

    Arterials always ship; local roads are thinned, because 2,500 polylines is
    more than the map needs to read as a road network.
    """
    rg = session.rg
    open_, flooded, disabled = [], [], []
    for u, v, e in rg.G.edges(data=True):
        if e["road_class"] == "local" and not (e["flooded"] or e["disabled"]) and (u + v) % 3:
            continue
        a, b = rg.node_latlon(u), rg.node_latlon(v)
        seg = [[a[0], a[1]], [b[0], b[1]]]
        if e["disabled"]:
            disabled.append(seg)
        elif e["flooded"]:
            flooded.append(seg)
        else:
            open_.append(seg)
    return {
        "open": open_,
        "flooded": flooded,
        "disabled": disabled,
        "river": [[lat, lon] for lon, lat in rg.river],
        "bridges": [
            {
                "lat": rg.node_latlon(u)[0],
                "lon": rg.node_latlon(u)[1],
                "standing": not rg.G.edges[u, v].get("disabled", False),
            }
            for u, v in rg.bridges
            if rg.G.has_edge(u, v)
        ],
        "counts": {"open": len(open_), "flooded": len(flooded), "disabled": len(disabled)},
    }


def zone_view(session) -> dict:
    """Hexes carrying demand, with how much of it has been served.

    This is the equity heatmap: it shows who is being under-served right now,
    not who was under-served at the end.
    """
    from collections import defaultdict

    demanded: dict[str, int] = defaultdict(int)
    served: dict[str, int] = defaultdict(int)
    for d in session.demands():
        z = d.location.h3_cell
        if not z:
            continue
        demanded[z] += d.need.people
        if d.status is DemandStatus.RESOLVED:
            served[z] += d.need.people

    out = []
    for z, total in demanded.items():
        if total <= 0:
            continue
        out.append(
            {
                "h3": z,
                "boundary": [[lat, lon] for lat, lon in cell_boundary(z)],
                "people": total,
                "served": served.get(z, 0),
                "coverage": round(min(1.0, served.get(z, 0) / total), 3),
            }
        )
    out.sort(key=lambda r: r["coverage"])
    return {"zones": out, "count": len(out)}


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------


def metrics_view(session) -> dict:
    rows = session.demands()
    resolved = [d for d in rows if d.status is DemandStatus.RESOLVED]
    plan = session.plan

    solves = session.solve_ms_history[-30:]
    verif = (
        len([a for a in plan.assignments if a.kind is TaskKind.VERIFICATION]) if plan else 0
    )

    return {
        "clock_minutes": session.clock_min,
        "messages_ingested": sum(
            1 for p in session.sensing.processed if p.envelope.received_at <= session.now
        ),
        "messages_total": len(session.data.messages),
        "demand_records": len(rows),
        "collapse_ratio": round(
            sum(d.duplicate_collapse_count for d in rows) / max(1, len(rows)), 2
        ),
        "duplicates_collapsed": sum(d.duplicate_collapse_count - 1 for d in rows),
        "people_outstanding": sum(
            d.need.people for d in rows if d.status is DemandStatus.UNASSIGNED
        ),
        "people_served": sum(d.need.people for d in resolved),
        "resolved": len(resolved),
        "in_flight": len(session.in_flight),
        "verification_dispatched": verif,
        "mean_confidence": round(
            sum(d.quantity_confidence for d in rows) / max(1, len(rows)), 3
        ),
        "mean_trust": round(sum(d.trust_score for d in rows) / max(1, len(rows)), 3),
        "solve_ms_last": round(solves[-1], 1) if solves else 0.0,
        "solve_ms_mean": round(sum(solves) / len(solves), 1) if solves else 0.0,
        "audit_entries": session.audit.count(),
        "confidence_histogram": _histogram([d.quantity_confidence for d in rows]),
        "trust_histogram": _histogram([d.trust_score for d in rows]),
        "resolution_mix": dict(Counter(d.location.resolution.value for d in rows)),
        "reserve": None
        if not plan or not plan.reserve
        else {
            "assets_held": plan.reserve.assets_held,
            "total_assets": plan.reserve.total_assets,
        },
    }


def _histogram(values, bins: int = 10) -> list[dict]:
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        n = sum(1 for v in values if lo <= v < hi or (i == bins - 1 and v == 1.0))
        out.append({"bin": f"{lo:.1f}", "lower": round(lo, 2), "count": n})
    return out
