"""PHAROS command line.

    pharos run       one configuration, one scenario, one metrics row
    pharos ablate    every configuration across several seeds, as a table
    pharos dedupe    the deduplication comparison - the headline slide
    pharos load      throughput and latency at 40,000 messages
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

DEFAULT_SCENARIO = "services/simulator/scenarios/kerala_flood_demo.yaml"

# The ablation table, in the order it should be read: baselines first, then the
# full system, then one row per novelty component removed.
ABLATION_ORDER = [
    "fifo",
    "nearest",
    "no_dedup",
    "no_calibration",
    "no_confidence",
    "no_verification",
    "no_trust",
    "no_equity",
    "full",
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pharos", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run one configuration end to end")
    r.add_argument("--scenario", default=DEFAULT_SCENARIO)
    r.add_argument("--config", default="full")
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--verbose", action="store_true")
    r.add_argument("--json", action="store_true", help="print the full metrics row")

    a = sub.add_parser("ablate", help="every configuration, several seeds, one table")
    a.add_argument("--scenario", default=DEFAULT_SCENARIO)
    a.add_argument("--configs", default=",".join(ABLATION_ORDER))
    a.add_argument("--seeds", default="42,43,44")
    a.add_argument("--out", default="data/results/ablation.json")

    d = sub.add_parser("dedupe", help="naive versus deduplicated demand")
    d.add_argument("--scenario", default=DEFAULT_SCENARIO)
    d.add_argument("--seed", type=int, default=42)

    lo = sub.add_parser("load", help="throughput and latency at full scale")
    lo.add_argument("--scenario", default="services/simulator/scenarios/kerala_flood_v1.yaml")

    args = ap.parse_args(argv)
    return {"run": _run, "ablate": _ablate, "dedupe": _dedupe, "load": _load}[args.cmd](args)


# --------------------------------------------------------------------------


def _run(args) -> int:
    from . import harness

    configs = harness.configurations()
    if args.config not in configs:
        print(f"unknown config {args.config!r}; have {', '.join(sorted(configs))}", file=sys.stderr)
        return 2

    print(f"scenario {Path(args.scenario).stem}  config {args.config}")
    row = harness.run(args.scenario, configs[args.config], seed=args.seed, verbose=args.verbose)
    harness.append_result(row)

    if args.json:
        import json

        print(json.dumps(row.to_dict(), indent=2))
        return 0

    _print_row(row)
    return 0


def _print_row(row) -> None:
    w = row.wasted
    print(f"\n  {row.messages:,} messages -> {row.demands:,} demand records "
          f"in {row.sensing_seconds:.1f}s")
    print(f"  {row.replans} replans, {row.solve_seconds_total:.1f}s solving "
          f"(p95 {row.solve_seconds_p95 * 1000:.0f}ms per replan)")
    print()
    print(f"  coverage                {row.coverage:7.1%}   "
          f"({row.people_reached:,} of {row.people_in_need:,} people)")
    print(f"  within urgency window   {row.coverage_within_window:7.1%}")
    print(f"  worst-off zone decile   {row.worst_off_zone_coverage:7.1%}")
    print(f"  median time to reach    {row.median_time_to_reach_min:7.1f} min")
    print(f"  p95 time to dispatch    {row.p95_time_to_first_assignment_min:7.1f} min")
    print()
    print(f"  wasted sorties          {w.get('wasted_sortie_fraction', 0):7.1%}   "
          f"(hoax {w.get('hoax_sorties', 0)}, duplicate {w.get('duplicate_sorties', 0)}, "
          f"stale {w.get('stale_sorties', 0)} of {w.get('total_sorties', 0)})")
    v = row.verification
    print(f"  verification tasks      {v.get('verification_tasks', 0):7}   "
          f"({v.get('verification_on_hoax', 0)} of them on hoaxes)")
    print()
    dd = row.dedup
    print(f"  dedup precision/recall  {dd.get('precision', 0):.3f} / {dd.get('recall', 0):.3f}"
          f"   collapse {dd.get('collapse_ratio', 1):.2f}x")
    cal = row.calibration
    if cal:
        print(f"  calibration ECE         {cal.get('ece', 0):.3f}   "
              f"Brier {cal.get('brier', 0):.3f}   (n={cal.get('n', 0)})")
    if row.geo:
        print("\n  geo resolution honesty - claimed level versus measured error:")
        for level in ("point", "building", "street", "ward", "unknown"):
            g = row.geo.get(level)
            if g:
                print(f"    {level:9} n={g['n']:5}  median {g['median_m']:8.0f}m  "
                      f"p90 {g['p90_m']:8.0f}m")


# --------------------------------------------------------------------------


def _ablate(args) -> int:
    import json

    from . import harness

    configs = harness.configurations()
    names = [n.strip() for n in args.configs.split(",") if n.strip()]
    seeds = [int(x) for x in args.seeds.split(",")]

    unknown = [n for n in names if n not in configs]
    if unknown:
        print(f"unknown configs: {', '.join(unknown)}", file=sys.stderr)
        return 2

    print(f"ablation over {len(names)} configurations x {len(seeds)} seeds "
          f"on {Path(args.scenario).stem}\n")

    rows: dict[str, list] = {}
    for name in names:
        rows[name] = []
        for seed in seeds:
            row = harness.run(args.scenario, configs[name], seed=seed)
            harness.append_result(row)
            rows[name].append(row)
            print(f"  {name:16} seed {seed}  {row.headline()}")

    print()
    _print_ablation(rows, seeds)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({k: [r.to_dict() for r in v] for k, v in rows.items()}, indent=2)
    )
    print(f"\nwritten to {out}")
    return 0


def _print_ablation(rows: dict[str, list], seeds) -> None:
    """Mean and spread across seeds. A single-seed result is not a result."""
    hdr = (
        f"{'configuration':18} {'coverage':>16} {'in-window':>16} {'worst zone':>16} "
        f"{'median TTR':>14} {'wasted':>14}"
    )
    print(hdr)
    print("-" * len(hdr))

    for name, rs in rows.items():
        print(
            f"{name:18} "
            f"{_ms(rs, 'coverage', pct=True):>16} "
            f"{_ms(rs, 'coverage_within_window', pct=True):>16} "
            f"{_ms(rs, 'worst_off_zone_coverage', pct=True):>16} "
            f"{_ms(rs, 'median_time_to_reach_min'):>14} "
            f"{_ms([r for r in rs], 'wasted', pct=True, key='wasted_sortie_fraction'):>14}"
        )
    print(f"\n  n={len(seeds)} seeds; +/- is the spread across them, not a confidence interval")


def _ms(rows, attr, pct=False, key=None) -> str:
    vals = []
    for r in rows:
        v = getattr(r, attr)
        if key:
            v = v.get(key, 0.0)
        vals.append(float(v))
    if not vals:
        return "-"
    m = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return f"{m:.1%} ±{sd:.1%}" if pct else f"{m:.1f} ±{sd:.1f}"


# --------------------------------------------------------------------------


def _dedupe(args) -> int:
    """The headline slide: what duplicate demand costs in physical assets."""
    from . import harness

    configs = harness.configurations()
    naive = harness.run(args.scenario, configs["no_dedup"], seed=args.seed)
    full = harness.run(args.scenario, configs["full"], seed=args.seed)

    print(f"\n{'':34} {'naive demand':>16} {'deduplicated':>16}")
    print("-" * 68)
    rows = [
        ("demand records", f"{naive.demands:,}", f"{full.demands:,}"),
        ("sorties flown", f"{naive.wasted.get('total_sorties', 0):,}",
         f"{full.wasted.get('total_sorties', 0):,}"),
        ("wasted on duplicate visits", f"{naive.wasted.get('duplicate_sorties', 0):,}",
         f"{full.wasted.get('duplicate_sorties', 0):,}"),
        ("seats committed to nobody", f"{naive.wasted.get('duplicate_seats', 0):,}",
         f"{full.wasted.get('duplicate_seats', 0):,}"),
        ("people reached", f"{naive.people_reached:,}", f"{full.people_reached:,}"),
        ("coverage", f"{naive.coverage:.1%}", f"{full.coverage:.1%}"),
        ("worst-off zone decile", f"{naive.worst_off_zone_coverage:.1%}",
         f"{full.worst_off_zone_coverage:.1%}"),
        ("median time to reach", f"{naive.median_time_to_reach_min:.1f} min",
         f"{full.median_time_to_reach_min:.1f} min"),
    ]
    for label, a, b in rows:
        print(f"{label:34} {a:>16} {b:>16}")
    print("\n  scenario duplicate rate is set to 0.25, the documented "
          "keralarescue.in figure,\n  with social amplification on top.")
    return 0


def _load(args) -> int:
    """Throughput and end-to-end latency at full scale."""
    import time

    from pharos_sensing.pipeline import SensingConfig, SensingPipeline

    from . import generator, spec

    s = spec.load(args.scenario)
    print(f"load test: {Path(args.scenario).stem}\n")

    t = time.perf_counter()
    data = generator.generate(s)
    gen_s = time.perf_counter() - t
    print(f"  generated {len(data.messages):,} messages from {len(data.truth):,} real events "
          f"in {gen_s:.1f}s")

    pipe = SensingPipeline(data.gazetteer, s.region.centre, SensingConfig())
    t = time.perf_counter()
    res = pipe.process(list(data.messages), now=max(m.received_at for m in data.messages),
                       t0=data.t0)
    sense_s = time.perf_counter() - t

    print(f"  sensing   {len(data.messages):,} messages -> {len(res.demands):,} demands "
          f"in {sense_s:.1f}s")
    print(f"\n  sustained throughput    {len(data.messages) / sense_s:,.0f} messages/sec")
    print(f"  mean per-message cost   {sense_s / len(data.messages) * 1000:.3f} ms")
    print(f"  collapse ratio          {len(data.messages) / max(1, len(res.demands)):.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
