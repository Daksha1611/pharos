"""Why the deduplication gate is missing or over-merging, in three numbers."""

from collections import Counter, defaultdict

from pharos_sensing.dedupe.cluster import metres
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, spec

d = generator.generate(spec.load("services/simulator/scenarios/kerala_flood_demo.yaml"))
now = max(m.received_at for m in d.messages)
p = SensingPipeline(d.gazetteer, d.spec.region.centre, SensingConfig())
r = p.process(list(d.messages), now=now, t0=d.t0)
labels = d.message_truth_map()

per_lm = Counter(t.landmark.name for t in d.truth)
print(f"1. gazetteer collision: {len(d.truth)} events over {len(d.gazetteer)} landmarks")
print(f"   mean events per landmark {len(d.truth)/len(d.gazetteer):.1f}, max {max(per_lm.values())}")

lv = Counter(pm.location.resolution.value for pm in r.processed)
n = len(r.processed)
print(f"\n2. pile-up: {lv['unknown']} messages ({lv['unknown']/n:.0%}) land on the identical")
print("   region centroid, so the distance gate separates them not at all")

by_truth = defaultdict(list)
for pm in r.processed:
    by_truth[labels[pm.envelope.message_id]].append(pm)

seps = []
for g in by_truth.values():
    known = [x for x in g if x.location.resolution.value != "unknown"]
    for i in range(len(known)):
        for j in range(i + 1, len(known)):
            seps.append(
                metres(
                    known[i].location.lat, known[i].location.lon,
                    known[j].location.lat, known[j].location.lon,
                )
            )
seps.sort()
print(f"\n3. same-event separation after geo-resolution (n={len(seps)}):")
for q in (0.5, 0.75, 0.9, 0.95):
    print(f"   p{int(q*100)}: {seps[int(len(seps)*q)]:7.0f}m")
print(f"   -> a 350m gate misses {sum(1 for s in seps if s > 350)/max(1,len(seps)):.0%} of true pairs")
