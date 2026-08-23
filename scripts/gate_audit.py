"""Which gate condition rejects true duplicate pairs, and how many.

Over-merging is the dangerous error, so the gate should be strict - but only
where strictness buys precision. This says which condition is actually paying
for itself, and which one is just losing recall.
"""

from collections import Counter, defaultdict

from pharos_sensing.dedupe import cluster as C
from pharos_sensing.dedupe.embed import EmbedInput
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, spec

d = generator.generate(spec.load("services/simulator/scenarios/kerala_flood_demo.yaml"))
p = SensingPipeline(d.gazetteer, d.spec.region.centre, SensingConfig())
proc = [p._process_one(m, d.t0) for m in d.messages]
vecs = p.embedder.encode(
    [
        EmbedInput(
            x.envelope.text_for_analysis(),
            x.extraction.need_type,
            x.extraction.people,
            tuple(x.extraction.vulnerability_flags),
            x.extraction.medical_urgency,
        )
        for x in proc
    ]
)
items = [
    C.ClusterItem(
        key=x.envelope.message_id,
        lat=x.location.lat,
        lon=x.location.lon,
        minutes=x.minutes,
        vector=vecs[i],
        need_type=x.extraction.need_type.value,
        people=x.extraction.people,
        people_confident=x.extraction.people_raw >= 0.55,
        resolution=x.location.resolution.value,
    )
    for i, x in enumerate(proc)
]

labels = d.message_truth_map()
by_truth = defaultdict(list)
for i, x in enumerate(proc):
    by_truth[labels[x.envelope.message_id]].append(i)

prm = C.DedupeParams()
reasons: Counter = Counter()
total = 0

for idxs in by_truth.values():
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            x, y = items[idxs[a]], items[idxs[b]]
            total += 1
            sim = float(x.vector @ y.vector)

            if abs(x.minutes - y.minutes) > prm.window_min:
                reasons["time window"] += 1
                continue
            if x.need_type != y.need_type:
                reasons["need type mismatch"] += 1
                continue
            if x.people_confident and y.people_confident and x.people > 0 and y.people > 0:
                lo, hi = sorted((x.people, y.people))
                if hi > lo * prm.max_headcount_ratio:
                    reasons["headcount ratio"] += 1
                    continue
            if x.locatable and y.locatable:
                r = prm.radius_m + x.uncertainty_m + y.uncertainty_m
                if C.metres(x.lat, x.lon, y.lat, y.lon) > r:
                    reasons["distance"] += 1
                    continue
                if sim < prm.sim_threshold:
                    reasons[f"similarity (<{prm.sim_threshold})"] += 1
                    continue
            else:
                if sim < prm.unlocatable_sim_threshold:
                    reasons[f"unlocatable similarity (<{prm.unlocatable_sim_threshold})"] += 1
                    continue
            reasons["PASSED"] += 1

print(f"true duplicate pairs: {total}\n")
for k, v in reasons.most_common():
    print(f"  {k:40} {v:7}  ({v / max(1, total):5.1%})")
