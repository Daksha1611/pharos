"""Show the clusters that mix two real events, and why they merged."""

from collections import Counter

from pharos_sensing.dedupe.cluster import metres
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, spec

d = generator.generate(spec.load("services/simulator/scenarios/kerala_flood_demo.yaml"))
now = max(m.received_at for m in d.messages)
r = SensingPipeline(d.gazetteer, d.spec.region.centre, SensingConfig()).process(
    list(d.messages), now=now, t0=d.t0
)
labels = d.message_truth_map()
truth = d.truth_by_id()

scored = []
for c in r.clusters:
    tids = [labels[r.processed[i].envelope.message_id] for i in c]
    distinct = len(set(tids))
    if distinct > 1:
        scored.append((len(c) * (len(c) - 1) // 2, distinct, c, tids))
scored.sort(reverse=True, key=lambda x: x[0])

print(f"{len(scored)} contaminated clusters; worst by pair count:\n")
for pairs, distinct, c, tids in scored[:4]:
    print(f"cluster of {len(c)} messages, {distinct} distinct real events, {pairs} pairs")
    counts = Counter(tids)
    for tid, n in counts.most_common():
        t = truth[tid]
        print(f"    {tid}  x{n:2}  {t.need.value:12} {t.people:3}p  "
              f"lm={t.landmark.name[:34] if t.landmark else '-'}")
    ex = [r.processed[i] for i in c[:4]]
    print("    sample resolutions:", [p.location.resolution.value for p in ex])
    print("    sample extracted n:", [p.extraction.people for p in ex])
    ll = [(p.location.lat, p.location.lon) for p in ex]
    if len(ll) > 1:
        print(f"    spread: {max(metres(*ll[0], *b) for b in ll[1:]):.0f}m")
    for p in ex[:3]:
        print(f"      \"{p.envelope.raw_text[:86]}\"")
    print()
