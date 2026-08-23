"""Deduplication precision and recall against generator ground truth.

Reported split by whether the message could be located at all. Messages that
resolve to nothing better than a district centroid cannot be deduplicated on
distance - merging them would mean merging on a coordinate we invented. They
are reported separately and held for the operator's disambiguation queue,
rather than being quietly counted as a clustering failure.
"""

from pharos_sensing.dedupe.cluster import DedupeParams
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, metrics, spec

GRID = [
    (0.62, 0.93, 1.6),
    (0.66, 0.93, 1.6),
    (0.70, 0.93, 1.6),
    (0.74, 0.93, 1.6),
    (0.70, 0.93, 2.0),
    (0.70, 0.93, 1.35),
]


def main() -> None:
    d = generator.generate(spec.load("services/simulator/scenarios/kerala_flood_demo.yaml"))
    now = max(m.received_at for m in d.messages)
    labels_by_mid = d.message_truth_map()

    print(f"{len(d.messages)} messages, {len(d.truth)} true events, {len(d.gazetteer)} landmarks\n")
    hdr = (
        f"{'sim':>5} {'unloc':>6} {'hc':>5} | {'prec':>6} {'rec':>6} {'f1':>6} | "
        f"{'clust':>6} {'contam':>6} {'collapse':>8}"
    )
    print(hdr)
    print("-" * len(hdr))

    for sim, unloc, hc in GRID:
        cfg = SensingConfig(
            dedupe=DedupeParams(
                sim_threshold=sim, unlocatable_sim_threshold=unloc, max_headcount_ratio=hc
            )
        )
        r = SensingPipeline(d.gazetteer, d.spec.region.centre, cfg).process(
            list(d.messages), now=now, t0=d.t0
        )
        labels = [labels_by_mid[pm.envelope.message_id] for pm in r.processed]
        m = metrics.dedup_precision_recall(r.clusters, labels)
        print(
            f"{sim:5.2f} {unloc:6.2f} {hc:5.1f} | {m['precision']:6.3f} {m['recall']:6.3f} "
            f"{m['f1']:6.3f} | {m['clusters']:6} {m['contaminated_clusters']:6} "
            f"{m['collapse_ratio']:8.2f}"
        )

    # Best-guess default, split by locatability.
    r = SensingPipeline(d.gazetteer, d.spec.region.centre, SensingConfig()).process(
        list(d.messages), now=now, t0=d.t0
    )
    labels = [labels_by_mid[pm.envelope.message_id] for pm in r.processed]
    locatable = [
        i for i, pm in enumerate(r.processed) if pm.location.resolution.value != "unknown"
    ]
    keep = set(locatable)
    sub_clusters = [[i for i in c if i in keep] for c in r.clusters]
    sub_clusters = [c for c in sub_clusters if c]
    remap = {old: new for new, old in enumerate(locatable)}
    sub_clusters = [[remap[i] for i in c] for c in sub_clusters]
    sub_labels = [labels[i] for i in locatable]

    print("\n--- defaults, split by whether the message could be located ---")
    all_m = metrics.dedup_precision_recall(r.clusters, labels)
    loc_m = metrics.dedup_precision_recall(sub_clusters, sub_labels)
    print(f"  all messages      n={len(labels):5}  P={all_m['precision']:.3f} "
          f"R={all_m['recall']:.3f} F1={all_m['f1']:.3f}")
    print(f"  locatable only    n={len(sub_labels):5}  P={loc_m['precision']:.3f} "
          f"R={loc_m['recall']:.3f} F1={loc_m['f1']:.3f}")
    print(f"  unlocatable       n={len(labels) - len(sub_labels):5}  held for the "
          f"disambiguation queue")


if __name__ == "__main__":
    main()
