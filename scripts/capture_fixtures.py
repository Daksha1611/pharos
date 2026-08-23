"""Freeze a live session into fixtures for the console's DEMO MODE.

DEMO MODE is a safety net, not a shortcut. The console normally runs against
the live API; if that process dies thirty seconds before the pitch, the
operator flips one switch and the whole screen still works off these files.

Because the fixtures are captured from the real endpoints rather than written
by hand, they match the schema exactly - so LIVE and DEMO render through the
same code, and a fixture that drifts from the API is caught the next time this
runs.

    uv run python scripts/capture_fixtures.py          # API on :8000
    uv run python scripts/capture_fixtures.py --tick 7 # advance first
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8000"
OUT = Path("web/console/src/mock/fixtures.json")

# Trimmed so the bundle stays reasonable. The console never shows more than a
# couple of hundred rows at once anyway.
DEMAND_LIMIT = 120
DETAIL_COUNT = 12


def get(path: str):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=30) as fh:
        return json.loads(fh.read())


def post(path: str):
    req = urllib.request.Request(f"{BASE}{path}", method="POST")
    with urllib.request.urlopen(req, timeout=180) as fh:
        return json.loads(fh.read())


def wait_ready(timeout: float = 300.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = get("/api/status")
        except urllib.error.URLError:
            print("  waiting for the API to accept connections…")
            time.sleep(4)
            continue
        if s["phase"] == "ready":
            return
        if s["phase"] == "error":
            raise SystemExit(f"session failed: {s['detail']}")
        print(f"  {s['detail']} ({s['progress'] * 100:.0f}%)")
        time.sleep(4)
    raise SystemExit("timed out waiting for the session")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tick", type=int, default=0, help="replans to advance before capturing")
    ap.add_argument("--reset", action="store_true", help="reset the clock first")
    args = ap.parse_args()

    print(f"capturing from {BASE}")
    wait_ready()

    if args.reset:
        print("  resetting")
        post("/api/control/reset")
    for i in range(args.tick):
        print(f"  tick {i + 1}/{args.tick}")
        post("/api/control/tick")

    print("  reading endpoints")
    fixtures = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": get("/api/status"),
        "scenario": get("/api/scenario"),
        "demands": get(f"/api/demands?limit={DEMAND_LIMIT}"),
        "plan": get("/api/plan"),
        "suggestion": get("/api/suggestion"),
        "assets": get("/api/assets"),
        "roads": get("/api/roads"),
        "zones": get("/api/zones"),
        "metrics": get("/api/metrics"),
        "events": get("/api/events"),
        "audit": get("/api/audit?limit=40"),
        "details": {},
    }

    ids = [d["demand_id"] for d in fixtures["demands"]["demands"][:DETAIL_COUNT]]
    for did in ids:
        fixtures["details"][did] = get(f"/api/demands/{did}")
    print(f"  captured {len(ids)} full demand records")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixtures, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024
    print(f"\nwrote {OUT} ({size_kb:.0f} KB)")
    print(f"  {fixtures['demands']['total']} demands, "
          f"{fixtures['plan']['counts']['rescue']} rescue assignments, "
          f"clock at T+{fixtures['status']['clock_minutes']:.0f}m")


if __name__ == "__main__":
    main()
