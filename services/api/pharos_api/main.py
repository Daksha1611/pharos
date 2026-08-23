"""PHAROS operations API.

One process, one live scenario, SQLite and an in-memory queue. Start it with

    make api

and the console at http://localhost:5173 drives it.

The session loads in a background thread because generating 5,500 messages and
running them through sensing takes about fifteen seconds; the console polls
`/api/status` and shows progress rather than hanging on a request.
"""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .session import Session
from .views import (
    asset_view,
    demand_detail,
    demand_view,
    metrics_view,
    plan_view,
    road_view,
    suggestion_view,
    zone_view,
)

SCENARIO = os.getenv("PHAROS_SCENARIO", "services/simulator/scenarios/kerala_flood_demo.yaml")

session = Session(SCENARIO)
sockets: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
    threading.Thread(target=session.load, name="pharos-load", daemon=True).start()
    yield


app = FastAPI(title="PHAROS", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# status and scenario
# --------------------------------------------------------------------------


@app.get("/api/status")
def status():
    s = session.status
    body = {"phase": s.phase, "detail": s.detail, "progress": s.progress}
    if session.ready:
        body |= {
            "clock_minutes": session.clock_min,
            "horizon_minutes": session.horizon_min,
            "clock_iso": session.now.isoformat(),
            "tick_minutes": session.tick_minutes,
            "equity_weight": session.solver.equity_weight,
            "mode": session.plan.mode.value if session.plan else "autonomous",
            "banner": session.plan.banner if session.plan else None,
        }
    return body


@app.get("/api/scenario")
def scenario():
    _require_ready()
    s = session.spec
    return {
        "name": s.name,
        "seed": s.seed,
        "centre": list(s.region.centre),
        "radius_km": s.region.radius_km,
        "h3_resolution": s.region.h3_resolution,
        "duration_hours": s.duration_hours,
        "replan_minutes": s.replan_minutes,
        "messages_total": len(session.data.messages),
        "true_events": len(session.data.truth),
        "demand_records": len(session.sensing.demands),
        "gazetteer_entries": len(session.data.gazetteer),
        "sensing_seconds": round(getattr(session, "sensing_seconds", 0.0), 2),
        "duplicate_rate": s.messages.duplicate_rate,
        "hoax_rate": s.messages.hoax_rate,
        "language_mix": s.messages.language_mix,
        "assets": {a.type: a.count for a in s.assets},
        "t0": session.data.t0.isoformat(),
    }


@app.get("/api/roads")
def roads(bbox: str | None = None):
    """Road geometry for the map, thinned so the browser can draw it."""
    _require_ready()
    return road_view(session, bbox)


@app.get("/api/zones")
def zones():
    _require_ready()
    return zone_view(session)


# --------------------------------------------------------------------------
# demand, assets, plan
# --------------------------------------------------------------------------


@app.get("/api/demands")
def demands(
    status_filter: str | None = Query(None, alias="status"),
    need: str | None = None,
    zone: str | None = None,
    min_confidence: float = 0.0,
    max_confidence: float = 1.0,
    min_trust: float = 0.0,
    resolution: str | None = None,
    search: str | None = None,
    limit: int = 300,
    offset: int = 0,
):
    _require_ready()
    return demand_view(
        session,
        status=status_filter,
        need=need,
        zone=zone,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        min_trust=min_trust,
        resolution=resolution,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/api/demands/{demand_id}")
def demand(demand_id: str):
    """Full record plus provenance: every source message, as the citizen wrote it."""
    _require_ready()
    out = demand_detail(session, demand_id)
    if out is None:
        raise HTTPException(404, f"no demand {demand_id}")
    return out


@app.get("/api/assets")
def assets():
    _require_ready()
    return asset_view(session)


@app.get("/api/plan")
def plan():
    _require_ready()
    return plan_view(session)


@app.get("/api/suggestion")
def suggestion():
    """The single decision this replan most wants a human to look at."""
    _require_ready()
    return suggestion_view(session)


@app.get("/api/metrics")
def metrics():
    _require_ready()
    return metrics_view(session)


@app.get("/api/audit")
def audit(limit: int = 60):
    _require_ready()
    return [
        {
            "id": e.id,
            "at": e.created_at,
            "actor": e.actor,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "evidence": e.evidence,
        }
        for e in session.audit.recent(limit)
    ]


@app.get("/api/events")
def events():
    _require_ready()
    return session.events[-40:]


# --------------------------------------------------------------------------
# controls
# --------------------------------------------------------------------------


@app.post("/api/control/tick")
async def tick(minutes: float | None = None):
    _require_ready()
    await _run(session.tick, minutes)
    await _broadcast("plan")
    return status()


@app.post("/api/control/equity")
async def equity(weight: float):
    _require_ready()
    await _run(session.set_equity, weight)
    await _broadcast("plan")
    return plan_view(session)


@app.post("/api/control/replan")
async def replan():
    _require_ready()
    await _run(session.replan, "operator requested")
    await _broadcast("plan")
    return plan_view(session)


@app.post("/api/control/break-bridge")
async def break_bridge():
    """Collapse a river crossing. The network's chokepoints are real, so this
    genuinely changes what is reachable rather than nudging travel times."""
    _require_ready()
    out = await _run(session.break_bridge)
    await _broadcast("roads")
    return out


@app.post("/api/control/redteam")
async def redteam(attack: str = "hoax_cluster"):
    _require_ready()
    out = await _run(session.inject_hoax, attack)
    await _broadcast("plan")
    return out


@app.post("/api/control/confidence")
async def confidence(cap: float | None = None):
    """Force intake confidence down to demonstrate graceful degradation."""
    _require_ready()
    await _run(session.set_confidence_floor, cap)
    await _broadcast("plan")
    return status()


@app.post("/api/control/override")
async def override(demand_id: str, asset_id: str, reason: str = "operator judgement"):
    _require_ready()
    await _run(session.override_assignment, demand_id, asset_id, reason)
    await _broadcast("plan")
    return plan_view(session)


@app.post("/api/control/reset")
async def reset():
    _require_ready()
    await _run(session.reset)
    await _broadcast("plan")
    return status()


# --------------------------------------------------------------------------
# websocket
# --------------------------------------------------------------------------


@app.websocket("/ws")
async def ws(socket: WebSocket):
    """Push replan results. The live replan is the best demo moment, and it has
    to be push - a poll makes it look like a page refresh."""
    await socket.accept()
    sockets.add(socket)
    try:
        await socket.send_json({"type": "hello", "status": status()})
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sockets.discard(socket)


async def _broadcast(kind: str) -> None:
    payload = {"type": kind, "status": status()}
    dead = []
    for s in list(sockets):
        try:
            await s.send_json(payload)
        except Exception:
            dead.append(s)
    for s in dead:
        sockets.discard(s)


# --------------------------------------------------------------------------


async def _run(fn, *args):
    """Solving blocks. Run it on a worker thread so the event loop keeps
    serving the console while a replan is in flight."""
    return await asyncio.to_thread(fn, *args)


def _require_ready() -> None:
    if session.status.phase == "error":
        raise HTTPException(503, f"session failed to load: {session.status.detail}")
    if not session.ready:
        raise HTTPException(503, f"session loading: {session.status.detail}")
