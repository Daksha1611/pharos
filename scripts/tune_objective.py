"""What the objective's travel weight and equity term cost and buy.

Two questions:
  - The solver is myopic. It optimises this round's value without pricing the
    fact that a 60-minute trip spends an asset for two hours, which is a sortie
    it cannot fly somewhere else. Does raising the travel weight fix it?
  - The maximin equity term adds a constraint per zone. What does it cost in
    solve time?
"""

from pharos_allocator.objective import SolverConfig, Weights
from pharos_sim import harness

SCENARIO = "services/simulator/scenarios/kerala_flood_demo.yaml"


def run(label: str, **kw) -> None:
    weights = Weights(time=kw.pop("time", 0.06))
    solver = SolverConfig(**kw)
    cfg = harness.RunConfig("full", solver=solver, weights=weights)
    row = harness.run(SCENARIO, cfg, seed=42)
    print(
        f"  {label:34} cov={row.coverage:6.1%}  in-window={row.coverage_within_window:6.1%}  "
        f"worst={row.worst_off_zone_coverage:5.1%}  ttr={row.median_time_to_reach_min:5.1f}m  "
        f"sorties={row.wasted.get('total_sorties', 0):4}  "
        f"solve_p95={row.solve_seconds_p95 * 1000:6.0f}ms"
    )


print("baseline for reference: nearest-asset reached 8.8% with 487 sorties\n")

print("travel weight (opportunity cost of spending an asset):")
for t in (0.06, 0.15, 0.30, 0.60):
    run(f"time={t}", time=t)

print("\nequity term cost:")
run("equity off", use_equity=False, equity_weight=0.0, time=0.30)
run("equity on, w=0.5", time=0.30)

print("\ncandidate window:")
for n in (300, 700, 1500):
    run(f"window={n}", max_candidate_demands=n, time=0.30)
