"""Solve time and quality after the equity coarsening."""

from pharos_allocator.objective import SolverConfig
from pharos_sim import harness

SC = "services/simulator/scenarios/kerala_flood_demo.yaml"
CASES = [
    ("equity res7, 60 zones", {}),
    ("equity res8, 200 zones", {"equity_resolution": 8, "equity_max_zones": 200}),
    ("equity off", {"use_equity": False, "equity_weight": 0.0}),
]
for label, kw in CASES:
    row = harness.run(SC, harness.RunConfig("full", solver=SolverConfig(**kw)), seed=42)
    print(
        f"  {label:26} cov={row.coverage:6.1%} urgent={row.urgent_coverage_within_window:6.1%} "
        f"worst={row.worst_off_zone_coverage:5.1%} sorties={row.wasted.get('total_sorties', 0):4} "
        f"solve_p95={row.solve_seconds_p95 * 1000:6.0f}ms"
    )
