"""Sweep the deduplication gate against generator ground truth.

Over-merging is far more dangerous than under-merging, so read the precision
column first and treat recall as the thing being traded for it.
"""

import sys

from pharos_sensing.dedupe.cluster import DedupeParams
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, metrics, spec

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "services/simulator/scenarios/kerala_flood_demo.yaml"


def main() -> None:
    d = generator.generate(spec.load(SCENARIO))
    now = max(m.received_at for m in d.messages)
    labels_by_mid = d.message_truth_map()

    print(f"{len(d.messages)} messages, {len(d.truth)} true events\n")
    header = (
        f"{'sim':>5} {'rad_m':>6} {'win':>5} | {'prec':>6} {'rec':>6} {'f1':>6} | "
        f"{'clusters':>8} {'contam':>6} {'ratio':>6}"
    )
    print(header)
    print("-" * len(header))

    for sim in (0.58, 0.62, 0.68, 0.72, 0.78, 0.84):
        for rad, win in ((350, 90), (600, 120), (900, 150)):
            cfg = SensingConfig(
                dedupe=DedupeParams(sim_threshold=sim, radius_m=rad, window_min=win)
            )
            p = SensingPipeline(d.gazetteer, d.spec.region.centre, cfg)
            r = p.process(list(d.messages), now=now, t0=d.t0)
            labels = [labels_by_mid[pm.envelope.message_id] for pm in r.processed]
            m = metrics.dedup_precision_recall(r.clusters, labels)
            print(
                f"{sim:5.2f} {rad:6} {win:5} | {m['precision']:6.3f} {m['recall']:6.3f} "
                f"{m['f1']:6.3f} | {m['clusters']:8} {m['contaminated_clusters']:6} "
                f"{m['collapse_ratio']:6.2f}"
            )


if __name__ == "__main__":
    main()
