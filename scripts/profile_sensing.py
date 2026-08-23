"""Per-stage timing for the sensing pipeline."""
import sys
import time
from collections import Counter

from pharos_sensing.dedupe import cluster as C
from pharos_sensing.dedupe.embed import EmbedInput
from pharos_sensing.pipeline import SensingConfig, SensingPipeline
from pharos_sim import generator, spec

N = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
s = spec.load("services/simulator/scenarios/kerala_flood_demo.yaml")
d = generator.generate(s)
msgs = d.messages[:N]
now = max(m.received_at for m in msgs)
p = SensingPipeline(d.gazetteer, d.spec.region.centre, SensingConfig())

t = time.perf_counter(); proc = [p._process_one(m, d.t0) for m in msgs]
print(f"normalize+extract+geo : {time.perf_counter()-t:6.2f}s for {len(msgs)}")

t = time.perf_counter()
vecs = p.embedder.encode([EmbedInput(x.envelope.text_for_analysis(), x.extraction.need_type,
       x.extraction.people, tuple(x.extraction.vulnerability_flags), x.extraction.medical_urgency)
       for x in proc])
print(f"embed                 : {time.perf_counter()-t:6.2f}s")

items = [C.ClusterItem(key=x.envelope.message_id, lat=x.location.lat, lon=x.location.lon,
         minutes=x.minutes, vector=vecs[i], need_type=x.extraction.need_type.value,
         people=x.extraction.people, people_confident=x.extraction.people_raw >= 0.55,
         resolution=x.location.resolution.value) for i, x in enumerate(proc)]

t = time.perf_counter(); edges = C._candidate_edges(items, C.DedupeParams())
print(f"candidate edges       : {time.perf_counter()-t:6.2f}s -> {len(edges)} edges")

t = time.perf_counter(); comps = C._connected_components(len(items), edges)
print(f"components            : {time.perf_counter()-t:6.2f}s -> {len(comps)} comps, "
      f"largest {max(len(c) for c in comps)}")

t = time.perf_counter(); clusters = C._refine(comps, items, C.DedupeParams())
print(f"refine                : {time.perf_counter()-t:6.2f}s -> {len(clusters)} clusters, "
      f"largest {max(len(c) for c in clusters)}")

t = time.perf_counter(); [p._reconcile(c, proc, now) for c in clusters]
print(f"reconcile             : {time.perf_counter()-t:6.2f}s")
print("\ncluster size histogram:", Counter(len(c) for c in clusters).most_common(8))
