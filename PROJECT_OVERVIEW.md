# PHAROS — Prioritization and Hazard-Aware Resource Orchestration System

## What Is PHAROS?

PHAROS is an **AI-powered disaster response decision-support system** that solves the core operational problem of flood relief: *when 40,000 messages arrive in six hours from people who need help, and you have a fleet that can reach only a fraction of them — which ones need a boat in the next fifteen minutes?*

It takes **raw, noisy, multilingual distress messages** (SMS, social media, chat, phone transcripts, web forms, control-room entries) and turns them into **optimized rescue plans** — deciding which asset (boat, ambulance, truck) goes where, and justifying every decision.

**Context:** Built around the **Kerala 2018 floods** as the reference disaster. The scenario uses real parameters: documented duplicate rates from keralarescue.in (25%), real language distributions (English, Hindi, code-mixed), hoax rates from actual events, and fleet sizes modelled on the fishing boats that operated during the crisis.

---

## The Problem It Solves

During a flood disaster, responders face five simultaneous failures:

1. **Duplicate reports** — The same family is reported by neighbours, relatives, and social media. Without deduplication, each duplicate sends a separate boat — Kerala 2018 discovered 25% duplicates mid-crisis.
2. **Misinformation / hoaxes** — Fabricated dam alerts, phantom supply drops, and scam leads pull boats away from real families. Existing systems treat this as a content-moderation problem; PHAROS treats it as a **resource contention** problem.
3. **Imprecise locations** — Only ~35% of reports carry GPS coordinates. The rest name landmarks ("near the panchayat office") or give nothing at all. Plotting everything as a map pin creates the **Kerala supply-drop failure**: relief lands away from the target house because shared coordinates weren't precise enough.
4. **Uncertain headcounts** — "About 7 people" could be 5 or 12. A system that treats 7 as exact either under-provisions (arrives with too few seats) or over-credits uncertain reports.
5. **No justification** — Automated dispatch systems that cannot explain *why* they chose one assignment over another are not trusted by operators. And an operator who doesn't trust the system overrides it on instinct, which is worse.

---

## System Architecture

PHAROS is a **Python monorepo** using a `uv` workspace with five packages:

```
PHAROS/
├── packages/
│   └── pharos-core/          # Shared data contracts (the "seam")
├── services/
│   ├── sensing/              # Message intake → demand records
│   ├── allocator/            # Demand records → optimized rescue plan
│   ├── simulator/            # Scenario generation, evaluation, ablation
│   └── api/                  # FastAPI HTTP + WebSocket server
├── web/
│   └── console/              # React + TypeScript operator dashboard
├── data/                     # Road graph cache, audit DB, results
└── scripts/                  # Diagnostic and tuning utilities
```

### Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Data Models | Pydantic v2 |
| Solver | Google OR-Tools CP-SAT |
| Spatial Indexing | Uber H3 hexagonal grid |
| Road Network | NetworkX (Dijkstra shortest paths) |
| Embeddings (default) | Hashing embedder (character n-grams + semantic frame) |
| Embeddings (optional) | sentence-transformers/LaBSE (cross-lingual, 1.8 GB) |
| Clustering (default) | Gated union-find with centroid refinement |
| Clustering (optional) | HDBSCAN density-based clustering + FAISS approximate nearest-neighbor search |
| Calibration | scikit-learn Isotonic Regression |
| API | FastAPI + Uvicorn + WebSockets |
| Frontend | React 18, TypeScript, Vite, MapLibre GL, Recharts, TanStack Query |
| Audit | SQLAlchemy + SQLite |
| Package Management | uv workspace |

---

## The Two Halves

PHAROS has two independent subsystems that communicate through one shared contract — the **DemandRecord**. This is called "**The Seam**".

### 1. Sensing Layer (`pharos-sensing`)

**Pipeline:** `normalize → extract → geo-resolve → dedupe → reconcile → trust`

Takes raw `MessageEnvelope` objects and produces `DemandRecord` objects.

#### Stage 1: Text Normalization (`normalize/`)

- **Language Detection** (`language.py`): Lexicon-based scorer over function words that distinguishes English, Roman-script Hindi, and code-mixed text. Generic detectors fail on 10-word crisis SMS where Hindi is written in Roman script. Uses curated marker word sets (`HI_MARKERS`, `EN_MARKERS`) instead of ML models — fully deterministic and offline.
- **Text Normalizer** (`text.py`): SymSpell-style delete index for typo repair. Precomputes single-character deletions of a domain vocabulary (~2000 words), so lookup is a dict hit instead of edit-distance over the vocabulary. Also expands SMS shorthand (`pls` → `please`, `watr` → `water`, `amb` → `ambulance`). Gazetteer place names are added to the vocabulary so the corrector never "fixes" `Vaikom` into something else.

#### Stage 2: Triage Extraction (`triage/extract.py`)

**Not classification — extraction.** Outputs four separate heads, each with its own confidence score:

| Head | What It Extracts | How |
|---|---|---|
| **Need Type** | evacuation, medical, water, food, shelter, sanitation, missing_person, infrastructure | Weighted regex cue matching across English and Hindi. Confidence = share of winning type + margin over runner-up + absolute evidence strength. |
| **Headcount** | Number of people affected | Hierarchical pattern matching: first-person count ("we are 7") → number + person unit ("5 people trapped") → household count × 4.6 (Kerala census mean) → bare number → household prior (5). Each method carries its own confidence (0.93 down to 0.15). |
| **Vulnerability** | infant, elderly, pregnant, disabled, injured | Regex cue detection in English and Hindi. Union across cluster members (one mention of an infant is enough to plan for one). |
| **Medical Urgency** | none, mild, moderate, critical | Tiered cue matching: critical = unconscious/bleeding heavily/cardiac; moderate = injured/fracture/insulin; mild = sick/fever/unwell. |

**Key design decision:** Raw scores are systematically overconfident (like raw softmax). This is deliberate — calibration fixes it in the next stage.

#### Stage 3: Confidence Calibration (`triage/calibration.py`)

**Isotonic Regression** per extraction head, fit on held-out ground-truth data. Maps raw overconfident scores onto observed correctness rates: after calibration, "0.7 confidence" means "right about 70% of the time."

- Produces **reliability curves** (predicted probability vs. observed frequency) — belongs on a presentation slide
- Computes **Expected Calibration Error (ECE)** and **Brier Score** for evaluation
- Converts calibrated headcount confidence into a **(lower, point, upper) interval**: capacity is planned against `upper` (never under-provision), value is credited against `lower` (never over-count an uncertain demand)

#### Stage 4: Geo-Resolution Cascade (`geo/resolve.py`)

An ordered cascade that tries six methods, stops at the first hit, and **always records which step resolved it and at what resolution level**:

| Step | Method | Resolution Level | Confidence |
|---|---|---|---|
| 1 | Channel-attached coordinates | point/building/street/ward (based on accuracy claim) | 0.28–0.95 |
| 2 | Coordinates written in the text (regex) | point | 0.92 |
| 3 | Nominatim geocoder (optional, self-hosted) | building | 0.80 |
| 4 | **Local landmark gazetteer** | street | 0.65 |
| 5 | Sender cell region + generic place word | ward | 0.35 |
| 6 | Nothing resolved | unknown | 0.0 |

**Key rule:** Resolution is **never upgraded** to make a map look better. A ward-level demand renders as a hex, an unknown-level demand renders as a list row — never as a pin. *A pin is a promise.*

**Landmark Gazetteer** (`geo/gazetteer.py`): 900 deterministically generated landmarks for the Ernakulam district — panchayat offices, temples, mosques, ferry jetties, mills, bus stands, etc. with prefixed aliases in English, Malayalam, and Hindi. Uses a token-inverted index for fast matching (avoids 600 regex searches per message). For production, replace `build()` with a CSV load.

**Location Consensus:** When a cluster has multiple member locations, takes the finest resolution present and averages only the members that reached it. A GPS pin averaged with a ward centroid produces a point that is wrong in a way neither input was.

#### Stage 5: Duplicate Clustering (`dedupe/`)

**The gate is the whole trick.** Text similarity alone merges half a district into one demand. Four hard gates must all pass before two messages are merged:

1. **Resolution-aware spatial radius** — Base tolerance (180m) + each message's own positional uncertainty. A GPS-pinned report gets a tight gate; a landmark-resolved one gets a wider gate. Beyond 3km, never merge.
2. **Need type must agree** — A household needing both a boat AND a medic generates two separate demand records (served by different assets).
3. **Headcount must agree** — Within 1.6× ratio. This separates eight emergencies behind the same landmark.
4. **Unlocatable messages are NOT deduplicated** — ~25% of intake resolves to the district centroid. Merging them would mean merging on a coordinate we *invented*. They stay separate and are flagged for operator disambiguation.

**Embedding** (`dedupe/embed.py`): Two backends behind one interface:
- **Hashing Embedder** (default): Concatenates hashed character n-grams (lexical half, 256-dim) with the extracted semantic frame (need type one-hot + vulnerability flags + urgency + headcount log-bucket). The semantic half is what makes it cross-lingual: a Hindi and English report of the same event produce the same frame. Zero download, deterministic, runs offline.
- **LaBSE Embedder** (opt-in via `PHAROS_EMBEDDER=labse`): sentence-transformers/LaBSE, genuinely cross-lingual in the embedding itself. ~1.8GB download on first use.

**Two clustering paths:**

1. **Default — Gated union-find** (offline, deterministic): H3 hexagonal spatial blocking at multiple resolutions so a GPS-pinned report and a landmark-resolved one actually meet in a comparison block. Pairwise cosine similarity is computed within each block, and pairs that pass all four gates are connected. Connected components are found via union-find, then refined against the cluster centroid (anti-chaining: A→B similar and B→C similar does not make A and C the same emergency — members that fall away are split out as their own demand).

2. **Neural — HDBSCAN + FAISS** (optional, requires `pip install pharos-sensing[neural]`): When using the LaBSE embedder, the system can leverage **FAISS** (Facebook AI Similarity Search) for approximate nearest-neighbor lookup over the high-dimensional LaBSE embedding space, and **HDBSCAN** (Hierarchical Density-Based Spatial Clustering of Applications with Noise) for density-based clustering. HDBSCAN is particularly well-suited to this problem because it does not require specifying the number of clusters upfront (the number of distinct emergencies is unknown), it naturally identifies noise points (messages that don't belong to any cluster), and it handles clusters of varying density (a 40-message viral post vs. a 2-message household report). The spatial, temporal, need-type, and headcount gates still apply on top of HDBSCAN's output — the gates are not bypassed, they refine the density-based clusters.

**Measured thresholds:** Similarity threshold of 0.68 chosen by sweeping against generator ground truth — holds pairwise precision at 0.84 on locatable messages. Precision is the number to protect: a wrongly merged demand is a family nobody comes for.

#### Stage 6: Trust Scoring (`trust/score.py`)

Output is a **continuous score** (0 to 1), **never a binary verdict**, and it enters the **optimizer's objective** — not as a filter on the feed. A hoax at trust 0.15 contributes 15% of its apparent value and loses to any real demand nearby. **Suppressed, not deleted** — still visible to the operator.

Five components:

| Component | Weight | What It Measures |
|---|---|---|
| **Corroboration** | 0.28 | Independent voices (distinct senders), not message count. Saturates at 3 independent reporters. |
| **Diversity** | 0.24 | Normalized entropy over channels × sender concentration. Ten posts from one WhatsApp group = one voice; three from three channels = three. |
| **Consistency** | 0.18 | Agreement on need type and headcount across cluster members. Disagreement on need type is a strong signal of a merge error or embellishment. |
| **Freshness** | 0.22 | Exponential decay, **90-minute half-life** from last corroboration. At 3 hours, a lead is worth 25% of its original value. *This is the fix for the 2021 stale-lead failure* where leads stayed in circulation long after the bed/cylinder was gone. |
| **Propagation** | 0.08 | Burst detection: many messages from very few accounts in a tight window = coordinated amplification signature. |

A single uncorroborated report keeps a floor of 0.52 — most real emergencies are reported once, and that is not a red flag.

---

### 2. Allocation Engine (`pharos-allocator`)

Takes `DemandRecord` objects + fleet + road network → produces a `Plan` with justified `Assignment` objects.

#### The Solver (`solver.py`) — Google OR-Tools CP-SAT

A **Constraint Programming with Satisfiability** solver. The model:

**Decision Variables:**
- `x[demand, asset]` — binary: assign this physical asset to this demand for rescue
- `y[demand, verifier]` — binary: assign this verifier (operator/volunteer) to this demand for verification

**Key constraints:**
- Each demand gets **at most one action**: rescued OR verified, never both
- Capacity constraint per asset (seats per sortie)
- Reserve hedging constraint (hold fleet back under uncertainty)

**The Two Lines That Are the Whole Confidence Idea:**
- **Capacity is planned against `people_upper`** — never turn up with too few seats
- **Value is credited against `people_lower`** — never over-credit a guess

An uncertain demand therefore costs the same to serve but earns less, so the solver **naturally prefers confirmed demand** without any rule telling it to.

**Six Novelty Flags** (each is one row of the ablation table):

| Flag | What It Does |
|---|---|
| `use_confidence` | Headcount enters as an interval, not a point |
| `use_reserve` | Hold capacity back under uncertainty |
| `use_verification` | Uncertainty routes to verification dispatch |
| `use_trust` | Low trust suppresses asset commitment |
| `use_equity` | Per-zone deficit multiplier for fairness |
| `use_escalation` | Aging demand rises in the ordering |

**Objective Function:**
- Per-demand value = `urgency_weight × need_type_weight × (1 + vulnerability_bonus) × confirmed_headcount × trust_score × escalation_weight × equity_multiplier − time_penalty × travel_minutes`
- Trust multiplies value: a hoax at 0.15 trust contributes 15% of apparent value
- Verification value: proportional to the potential value × current doubt

**Equity:** Operator-controlled slider (0 = pure throughput, 1 = maximum fairness). Implemented as a per-zone deficit multiplier — zones served less get weighted up. Replaced a textbook maximin (which cost 8 of 10 seconds of solve time for zero measured effect).

**Graceful Degradation:** When mean intake confidence drops below 0.45, the system switches to `DECISION_SUPPORT` mode — stops auto-assigning and hands control back to the operator. "When the sensing layer loses confidence, the system stops assigning and hands control back. It does not guess."

**Performance:** Candidate window limits model to top-700 demands. Top-K pruning keeps nearest 10 assets per demand. Solves within 10 seconds.

#### Road Network (`graph.py`)

- **Synthetic graph** (default, offline): Deterministic grid with jitter, radial arterials, a meandering river with only 5 bridge crossings (chokepoints). Same seed = same graph.
- **Real OSM** (optional): OpenStreetMap extract via OSMnx, cached as pickle.

**Road degradation:**
- **Flooded edges**: Impassable to trucks/ambulances; boats can cross at 9 km/h. This asymmetry is why the solver's answer to a flood is not simply "everything got further away."
- **Disabled edges** (collapsed bridge): Nothing crosses, not even a boat.

#### Cost Matrix (`costmatrix.py`)

- One Dijkstra per (asset type, depot node) — co-located same-type assets share one run
- `RouteOracle` caches shortest-path distances across replans, invalidated only when the road state changes
- Verification assets have a flat 3-minute cost (phone call costs the same from anywhere)

#### Justification Engine (`justify.py`)

Every assignment carries machine-readable **reasons**:
- **Urgency** — need type and medical urgency with contribution share
- **Headcount** — interval with committed seats vs. credited people
- **Vulnerability** — flags present
- **Trust** — score with report count and channel diversity
- **Reachability** — which asset, how many minutes, over current road state
- **Location quality** — resolution level, method, geo confidence
- **Zone deficit** — equity contribution
- **Alternatives** — *what was rejected and why* (e.g., "truck-38 was closer at 12 min but was committed elsewhere or out of capacity")

**Unserved demands** also get explanations — silence about a demand nobody is coming for is how people get missed.

#### H3 Zoning (`zones.py`)

Uses Uber H3 hexagonal tessellation at resolution 8 (~0.7 km² cells). Equal-area cells make "worst-off zone" a defensible metric instead of an argument about ward boundaries.

---

### 3. Simulator & Evaluation (`pharos-sim`)

#### Scenario Generator (`generator.py`)

Generates a complete disaster scenario from a YAML spec:
- **1,700 ground-truth emergencies** (TruthDemand) with known locations, need types, headcounts, vulnerability flags
- **~6,000 messages** from those emergencies, with realistic: lognormal arrival curve peaking at hour 2, 25% duplicate rate, social media amplification (55% share fraction, mean 4 extra copies), language mix (45% English, 25% Hindi, 30% code-mixed), 35% with GPS coordinates, 55% mentioning landmarks, 3% hoaxes, typos (8%), SMS shorthand (15%)

#### Corpus (`corpus.py`)

Template-based message generation in English, Hindi, and code-mixed registers. Produces natural-sounding crisis text with place phrases, vulnerability mentions, and realistic corruption (typos, character drops, SMS shorthand).

#### Red Team (`redteam.py`)

Three attack types, each modelled on documented incidents:

| Attack | Real-World Source | Mechanism |
|---|---|---|
| **Hoax Cluster** | Kerala 2018 fabricated dam alerts | 40 messages from 2 accounts in 4 minutes. Content is indistinguishable from real; signature is entirely in corroboration structure. |
| **Amplification Cascade** | 2021 India COVID stale leads | A real, already-resolved case re-shared 25 times from 3 accounts until it dominates the map. |
| **Stale Reports** | 2021 oxygen/bed lead circulation | 20 genuine emergencies resolved hours ago, still circulating. No bad actor at all. |

#### Evaluation Harness (`harness.py`)

Runs a complete scenario end-to-end: generate → sense → build roads → replan at every tick → dispatch → collect metrics.

#### Metrics (`metrics.py`)

Three families of metrics:

**Operational:**
- Raw coverage (people reached / people in need)
- Coverage within urgency window (arriving late ≠ arriving)
- Urgent coverage within window (critical/moderate medical only)
- Urgency-weighted coverage (what the objective actually optimizes)
- Worst-off zone coverage (quartile — the equity metric)
- Zones reached fraction, Zone coverage Gini coefficient
- Median time to reach, P95 time to first assignment
- Wasted effort: hoax sorties, duplicate sorties, stale sorties, phantom seats

**Model:**
- Dedup pairwise precision/recall against ground truth
- Geo accuracy by resolution level (claimed vs. measured error)
- Extraction accuracy per field per confidence bucket
- Calibration ECE and Brier score

**System:**
- Throughput (messages/sec), solve time per replan

#### Ablation Table (`cli.py ablate`)

Runs every configuration across multiple seeds:
- **Baselines:** FIFO (first-in-first-served), Nearest-asset
- **Full system** (all features on)
- **Ablations:** no_dedup, no_calibration, no_confidence, no_verification, no_trust, no_equity

Each row removed is one claim, quantified. A single-seed result is not a result — uses 3 seeds with mean ± spread.

---

### 4. Operations API (`pharos-api`)

**FastAPI** server with HTTP REST + WebSocket push.

#### Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Session phase, clock, equity weight, mode, banner |
| `/api/scenario` | GET | Scenario metadata, message counts, language mix |
| `/api/demands` | GET | Filterable demand list (by status, need, zone, confidence, trust, resolution) |
| `/api/demands/{id}` | GET | Full record with provenance (every source message as the citizen wrote it) |
| `/api/assets` | GET | Fleet status |
| `/api/plan` | GET | Current plan with assignments and justifications |
| `/api/roads` | GET | Road geometry for map |
| `/api/zones` | GET | H3 zone data |
| `/api/metrics` | GET | Live operational metrics |
| `/api/audit` | GET | Audit trail |
| `/api/suggestion` | GET | Single highest-priority decision needing human review |
| `/api/control/tick` | POST | Advance scenario clock |
| `/api/control/equity` | POST | Set equity slider (0–1) |
| `/api/control/break-bridge` | POST | Collapse a river crossing |
| `/api/control/redteam` | POST | Inject hoax/amplification/stale attack |
| `/api/control/confidence` | POST | Force intake confidence down |
| `/api/control/override` | POST | Manual operator reassignment |
| `/api/control/reset` | POST | Reset scenario to zero |
| `/ws` | WebSocket | Push replan results to console |

#### Audit Trail (`audit.py`)

Every action — replan, equity change, bridge collapse, hoax injection, manual override — is logged to SQLite with actor, action, entity, and evidence. Immutable record.

#### Session (`session.py`)

Manages the live demo: scenario loading, clock advancement, fleet dispatch, asset return, scheduled road degradation, demand state tracking. Assets that finished a sortie return to depot; unresolved demands escalate over time.

---

### 5. Operator Console (`web/console/`)

**React 18 + TypeScript + Vite** single-page application.

- **Interactive Map** (MapLibre GL): Demands as pins (only if resolution is point/building), hex zones, road network, asset routes, river overlay
- **Demand Queue**: Filterable, sortable list with confidence/trust indicators
- **Detail Panel**: Full demand record with provenance (raw citizen texts), assignment trace with justification, alternatives considered
- **Equity Slider**: Operator-controlled efficiency ↔ equity trade-off, re-solves in real-time
- **Controls**: Play/Step (advance clock), Break Bridge, Inject Hoax, Drop Confidence, Reset
- **Metrics Dashboard**: Live coverage, waste, dedup, calibration stats
- **WebSocket**: Real-time push updates on every replan

---

## Data Models (The Seam — `pharos-core`)

Four fields on `DemandRecord` that do not exist in comparable systems:

| Field | What It Means | Who Consumes It |
|---|---|---|
| `duplicate_collapse_count` | How many raw reports merged into this demand | Dedup metrics, operator panel |
| `quantity_confidence` | Calibrated — 0.7 means right 70% of the time | Solver: interval hedging, reserve, verification routing |
| `trust_score` | Continuous, 0–1 — optimizer input, **never a filter** | Solver: suppresses value, never deletes |
| `location.resolution` | point / building / street / ward / unknown | Map rendering (pin vs. hex vs. list), dedupe gate width |

### Asset Types

| Type | Role | Can Cross Flooded Roads? |
|---|---|---|
| Boat | Water rescue | Yes (at 9 km/h) |
| Ambulance | Medical response | No |
| Truck | Supply/evacuation (40 people) | No |
| Helicopter | (defined but not in demo fleet) | N/A |
| **Operator** | Verification (phone call) | N/A (flat 3-min cost) |
| **Volunteer** | Verification (field check) | N/A (flat 3-min cost) |

Verification assets are dispatched by the **same solver** competing for the same scheduling budget. Uncertainty routes to verification; certainty routes to rescue.

---

## Demo Scenario: Kerala Flood

Defined in `kerala_flood_demo.yaml`:

- **Region:** Ernakulam district, Kerala (9.93°N, 76.27°E), 25km radius
- **Duration:** 6 hours
- **Messages:** 6,000 from ~1,700 real emergencies
- **Fleet:** 60 boats, 20 ambulances, 45 trucks, 8 operators, 14 volunteers across multiple depots
- **Road degradation:** 15% flooded at 1.5h, 30% at 3h
- **Replan interval:** Every 15 minutes

---

## How to Run

```bash
make demo          # API on :8000, Console on :5173
make api           # API only
make console       # Console only
make ablate        # Full ablation table, 3 seeds
make dedupe        # Naive vs. deduplicated comparison
make load          # 40,000-message throughput test
make test          # pytest
make lint          # ruff
```

No containers, no network required. Everything runs on a laptop offline.

---

## Key Design Principles

1. **Uncertainty is a first-class citizen** — Headcounts are intervals, not points. Confidence is calibrated. Trust is continuous, not binary. The system hedges rather than guessing.

2. **Suppression over deletion** — Hoaxes are suppressed (trust 0.15 → 15% value), never deleted. A hoax is resource contention, not a moderation problem.

3. **Visual honesty** — A ward-level location renders as a hex, never as a pin. A pin is a promise. This directly addresses the Kerala 2018 supply-drop failure.

4. **Every decision is justified** — Assignments carry reasons including alternatives rejected. Unserved demands carry explanations. Silence is how people get missed.

5. **Operator authority** — The equity slider, manual overrides, and decision-support mode ensure the operator owns the trade-offs. An automated decision an operator cannot override is not decision support.

6. **Measured, not asserted** — Every novelty claim is a flag that can be toggled off. The ablation table proves each claim with baselines and multiple seeds. "Compared to what?" has an answer.

7. **Graceful degradation** — When sensing confidence collapses, the system stops assigning and says so. It states its own limits rather than guessing.

---

## Dependencies

**Python packages:** pydantic, ortools (≥9.10), networkx (≥3.2), numpy (≥1.26), scikit-learn (≥1.5), h3 (≥4.1), fastapi (≥0.115), uvicorn, sqlalchemy (≥2.0), websockets, pyyaml

**Optional neural path** (`pip install pharos-sensing[neural]`): sentence-transformers (≥3.0) for LaBSE cross-lingual embeddings, torch (≥2.2) as the neural backend, faiss-cpu (≥1.8) for approximate nearest-neighbor search over embedding vectors, hdbscan (≥0.8) for density-based clustering that doesn't require a pre-set cluster count

**Frontend:** React 18, MapLibre GL, Recharts, TanStack React Query, Tailwind CSS, TypeScript, Vite
