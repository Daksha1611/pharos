# PHAROS: Full Project Presentation Guide

*This document contains the slide-by-slide narrative and key talking points for the complete PHAROS vision. It emphasizes the core innovations of the full system (dynamic reallocation and closed-loop verification) extending beyond the current proof-of-concept demo.*

---

## Slide 1: Title Slide
**PHAROS: Prioritization and Hazard-Aware Resource Orchestration System**
*Moving disaster response from reactive chaos to intelligent, dynamic orchestration.*

---

## Slide 2: The Core Problem: Disaster Resource Allocation
**We don't lack data or resources; we lack actionable signal and centralized orchestration.**
During crises like the 2018 Kerala floods, responders face systemic failures in resource allocation:
*   **The Allocation Bottleneck:** Government agencies, local hospitals, and rescue fleets have resources, but they operate in silos. Matching a decentralized supply of boats, ambulances, and food to a chaotic, unverified demand stream is nearly impossible without AI.
*   **Information Overload & Duplication:** 40,000 messages in 6 hours. Neighbours, relatives, and victims report the same incident, sending multiple boats to one house while others drown. (Historically, 25%+ are duplicates).
*   **The Misinformation Drain:** Fake alerts and "phantom supplies" aren't just bad data—they are a *resource contention* problem. A hoax pulls a real boat away from a real family.
*   **Imprecise Locations & Static Dispatching:** Mapping vague locations as precise pins leads to "supply drop failures," and dispatching a truck without monitoring road hazards means it gets stuck when a road floods 10 minutes later.

---

## Slide 3: Introducing PHAROS (The Full Vision)
**An AI-driven orchestration engine, not just a dashboard.**
PHAROS is a complete, closed-loop system that ingests chaotic data, extracts verified needs, dispatches physical assets, and continuously adapts to a changing environment. 

**The Core Loop:**
1.  **Sense:** Ingest from WhatsApp, SMS, X/Twitter, and control rooms.
2.  **Distill:** Deduplicate, geo-resolve, and score for trust.
3.  **Orchestrate:** Dynamically allocate and reallocate resources.
4.  **Verify:** Confirm resolution and free up assets.

---

## Slide 4: The Sensing Pipeline (Finding the Signal)
**Turning raw text into structured demand.**
*   **Cross-Lingual NLP:** Extracts Need Type (Evacuation, Medical, Food), Headcounts, and Vulnerabilities (infants, elderly) from code-mixed text (e.g., "Hindi in Roman script").
*   **Smart Deduplication:** Uses HDBSCAN density-based clustering and FAISS. It merges reports only if they pass strict spatial, temporal, and semantic gates. 
*   **Honest Geo-Resolution:** If a report says "Ernakulam district," PHAROS maps it as a broad zone (hex grid), not a fake point. *A pin on our map is a promise.*

---

## Slide 5: Trust as a Metric, Not a Filter
**Handling hoaxes and stale data.**
*   Instead of deleting suspicious messages (which might be real), PHAROS assigns a **Trust Score** (0.0 to 1.0).
*   **Corroboration & Diversity:** 10 WhatsApp messages from the same group count as 1 voice. 3 messages from different channels (SMS, Twitter, Call) count as highly trusted.
*   **Freshness Decay:** A report of "Need Oxygen" has a 90-minute half-life. If it's not corroborated, its priority naturally decays. This prevents fleets from chasing stale leads that were resolved hours ago.

---

## Slide 6: Centralized Pooling & Dynamic Reallocation (Core Innovation)
**Integrating all response assets into a single optimization engine and allocating by priority.**
*In the real-world PHAROS deployment, resource allocation spans across multiple emergency domains dynamically.*
*   **Unified Supply Pool:** PHAROS maintains a real-time inventory of diverse resources: NDRF (National Disaster Response Force) units, local hospitals, fire rescue teams, food/ration supplies, and government refugee shelters. 
*   **Priority-Based Matching:** The AI optimizer assigns resources strictly by calculated priority (e.g., Trapped under debris > Critical Fire > General Evacuation > Food/Shelters) rather than a flawed "first-come, first-served" basis.
*   **On-the-fly Rerouting (NDRF & Fire):** If an NDRF unit is en route to clear a minor road, but a building collapse with trapped victims is reported 2km away, PHAROS *reallocates* the heavy rescue unit instantly to the higher priority. 
*   **Hazard-Aware Routing & Logistics:** If satellite data indicates a bridge has collapsed, PHAROS reroutes supply trucks delivering rations or redirects evacuees to an alternative, accessible refugee camp. It automatically prioritizes NDRF engineering units to clear the blocked critical paths.

---

## Slide 7: Closed-Loop Verification (Core Innovation)
**How do we know the problem is actually solved?**
*A dispatch is not a resolution. PHAROS actively reconfirms status to free up assets.*
*   **Multi-Channel Polling:** The system can trigger automated SMS/WhatsApp check-ins to the original reporters: *"Has the boat arrived? Reply YES or NO."*
*   **Social Listening:** If the community self-rescues, they often post updates online. PHAROS detects "we are safe now" signals linked to the original cluster and cancels the dispatch.
*   **Verification Dispatches:** For high-uncertainty, high-impact claims (e.g., "100 people trapped, no corroboration"), PHAROS dispatches a low-cost "Verifier" (a drone or a local volunteer phone call) before committing a 40-person rescue truck.

---

## Slide 8: Explainable AI & Human Authority
**Decision support, not decision replacement.**
*   **Graceful Degradation:** If AI confidence drops below a safe threshold, PHAROS stops auto-assigning and switches to "Decision Support Mode," highlighting anomalies for the human operator.
*   **Explainability:** Every dispatch comes with a machine-readable justification. *(e.g., "NDRF Unit 2 dispatched: 80% trust, structural collapse, 12 min ETA. Fire team rejected due to lack of heavy equipment.")*
*   **Equity Slider:** Operators can adjust the algorithm in real-time. Slide to "Efficiency" to rescue the maximum number of people. Slide to "Equity" to ensure isolated, hard-to-reach zones aren't left without rations or shelter.

---

## Slide 9: Beyond the Demo: Future Capabilities
**Where PHAROS is heading for full-scale production.**
*   **Live Sensor & Imagery Ingestion:** Integrating real-time flood gauges and drone/satellite imagery (SAR) to automatically degrade the road network graph without human input.
*   **Predictive Pre-positioning:** Using weather models to pre-allocate boats to zones *before* the water rises, minimizing time-to-rescue.
*   **Mesh-Network Ready:** Designed so the core allocation engine can run on local edge devices when cell towers go down, syncing via mesh networks.

---

## Slide 10: Summary & Impact
*   **Without PHAROS:** Duplicates overwhelm dispatchers, fake news steals boats, and isolated communities are ignored.
*   **With PHAROS:** Verified signal, dynamic reallocation, confirmed resolutions, and transparent equity. 
*   **The Result:** Maximizing lives saved per physical asset deployed.

---

## Slide 11: Technical Architecture & System Flow (Full Scale)
**The models and infrastructure powering the production environment.**
*   **1. High-Throughput Intake:** Apache Kafka / AWS Kinesis for real-time event streaming from disparate sources (WhatsApp Business API, X/Twitter scrapers, webhooks).
*   **2. Sensing & NLP Pipeline:**
    *   **Text Normalization:** SymSpell-style algorithms for offline, ultra-fast typo repair.
    *   **Extraction:** Custom NER (Named Entity Recognition) and Regex cascades for extracting Need Type, Headcounts, and Vulnerability flags across code-mixed languages.
    *   **Calibration:** Scikit-learn (Isotonic Regression) to map raw extraction confidence to true probability.
*   **3. Geo-Resolution & Clustering:** 
    *   **Spatial Indexing:** Uber's **H3** Hexagonal hierarchical spatial index.
    *   **Embeddings & Deduplication:** Sentence-Transformers (**LaBSE**) for cross-lingual semantic embeddings, **FAISS** for fast nearest-neighbor search, and **HDBSCAN** for density-based clustering without predefined cluster counts.
*   **4. Dynamic Optimization Engine:** Google **OR-Tools (CP-SAT solver)** processing a constraint-programming model to balance capacity, priority, and reserve assets in continuous replan loops.
*   **5. Dynamic Routing:** NetworkX and OSMnx (OpenStreetMap) utilizing Dijkstra algorithms over a cost matrix that dynamically degrades based on live ingested hazard data (e.g., Synthetic Aperture Radar / drone feeds).
*   **6. Deployment & Infrastructure:** Microservices built on **FastAPI** (Python 3.11+), deployed on Kubernetes for horizontal scaling, with a **React/Vite/MapLibre GL** frontend communicating via WebSockets.

---

## Slide 12: The Seam — How Each DemandRecord Field Is Computed
**The DemandRecord is the data contract between sensing and allocation. These five fields don't exist in comparable systems.**

### `quantity_interval` (lower, point, upper)
*   **Stage:** Triage Extraction → Calibration
*   **How:** Hierarchical regex matching extracts a raw headcount (e.g., "we are 7 people" → 7, "a household" → 4.6 from Kerala census mean). The calibrated confidence is then used to compute a symmetric interval:
    *   `lower = point × confidence` (credited value — never over-count a guess)
    *   `upper = point / confidence` (planned capacity — never show up with too few seats)
*   **Why it matters:** The solver plans capacity against `upper` but credits value against `lower`. An uncertain "about 20 people" costs more to serve but earns less, so the optimizer naturally prefers confirmed demand.

### `quantity_confidence`
*   **Stage:** Triage Extraction → Isotonic Regression Calibration
*   **How:** Each extraction method carries a raw confidence (first-person count: 0.93, number + unit: 0.85, household prior: 0.15). These raw scores are **systematically overconfident**. Isotonic Regression (trained on held-out ground truth) maps them to calibrated probabilities — after calibration, "0.7 confidence" means "correct about 70% of the time."
*   **Metric:** Validated via Expected Calibration Error (ECE) and Brier Score on reliability curves.

### `trust_score` (0.0 – 1.0)
*   **Stage:** Trust Scoring (post-deduplication)
*   **How:** Weighted sum of five components:
    *   **Corroboration (0.28):** Count of independent senders (not messages). Saturates at 3.
    *   **Diversity (0.24):** Normalized entropy over channels × sender concentration. 10 WhatsApp posts from 1 group = 1 voice.
    *   **Freshness (0.22):** Exponential decay with 90-minute half-life from last corroboration. At 3 hours, a lead is worth 25%.
    *   **Consistency (0.18):** Agreement on need type and headcount across cluster members.
    *   **Propagation (0.08):** Burst detection — many messages from few accounts in a tight window = amplification signature.
*   **Floor:** A single uncorroborated report keeps 0.52 — most real emergencies are reported once.
*   **How the solver uses it:** Trust multiplies demand value. A hoax at 0.15 contributes 15% of its apparent value and loses to any real demand nearby. **Suppressed, never deleted.**

### `geo_resolution_level` (point | building | street | ward | unknown)
*   **Stage:** Geo-Resolution Cascade
*   **How:** A six-step ordered cascade — stops at the first hit:
    1. Channel-attached GPS coordinates → `point` (confidence 0.95)
    2. Coordinates parsed from text via regex → `point` (0.92)
    3. Nominatim geocoder (self-hosted) → `building` (0.80)
    4. Local landmark gazetteer (900 landmarks, token-inverted index) → `street` (0.65)
    5. Sender cell region + generic place word → `ward` (0.35)
    6. Nothing resolved → `unknown` (0.0)
*   **Key rule:** Resolution is never upgraded. A `ward`-level demand renders as a hex zone, never as a pin. A pin is a promise.

### `duplicate_collapse_count`
*   **Stage:** Deduplication Clustering
*   **How:** After HDBSCAN/union-find clustering, this field records how many raw messages were merged into this single demand record. Merging requires passing all four hard gates simultaneously:
    1. Spatial radius (180m base + each message's positional uncertainty, max 3km)
    2. Need type agreement
    3. Headcount ratio within 1.6×
    4. Unlocatable messages (resolved to district centroid) are never merged
*   **Anti-chaining:** Every member must resemble the cluster centroid, not just a neighbour. Prevents transitive drift.
*   **Why it matters:** A demand with `collapse_count = 12` means 12 independent reports confirmed the same event — this feeds directly into corroboration (trust) and tells the operator the signal is strong.
