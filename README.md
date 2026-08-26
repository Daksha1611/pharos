# PHAROS

**Prioritization and Hazard-Aware Resource Orchestration System**

> *When 40,000 distress messages arrive in six hours and your fleet can reach only a fraction of them — which ones need a boat in the next fifteen minutes?*

PHAROS is an AI-powered disaster response **decision-support system** that takes raw, noisy, multilingual distress messages and turns them into optimized, justified rescue plans.

Built around the **Kerala 2018 floods** as the reference disaster, using real parameters: documented duplicate rates from keralarescue.in (25%), real language distributions, hoax rates from actual events, and fleet sizes modelled on the fishing boats that operated during the crisis.

---

## The Problem

During a flood, responders face five simultaneous failures:

| Failure | Description |
|---|---|
| **Duplicates** | The same family is reported by neighbours, relatives, and social media — Kerala 2018 saw 25% duplicates discovered mid-crisis |
| **Misinformation** | Fabricated dam alerts and phantom supply drops pull assets away from real emergencies |
| **Imprecise locations** | Only ~35% of reports carry GPS coordinates; plotting everything as a pin creates the **Kerala supply-drop failure** |
| **Uncertain headcounts** | "About 7 people" could be 5 or 12 — over-provisioning and under-provisioning both cost lives |
| **No justification** | Systems that cannot explain *why* they chose one assignment over another are not trusted — and an operator who doesn't trust the system overrides it on instinct |

---

## System Architecture

PHAROS is a **Python monorepo** using a `uv` workspace with five packages, a React frontend, and a shared data contract at the center.

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
| Clustering (optional) | HDBSCAN + FAISS approximate nearest-neighbor |
| Calibration | scikit-learn Isotonic Regression |
| API | FastAPI + Uvicorn + WebSockets |
| Frontend | React 18, TypeScript, Vite, MapLibre GL, Recharts, TanStack Query |
| Audit | SQLAlchemy + SQLite |
| Package Management | uv workspace |

---

## How It Works

PHAROS has two independent subsystems connected by a single shared contract — the **DemandRecord** (called "The Seam").

### 1. Sensing Pipeline

`normalize → extract → calibrate → geo-resolve → deduplicate → trust`

Takes raw `MessageEnvelope` objects and produces `DemandRecord` objects.

**Stage 1 — Text Normalization:** SymSpell-style typo repair with a domain vocabulary (~2,000 words), SMS shorthand expansion, and lexicon-based language detection for English, Hindi, and code-mixed text.

**Stage 2 — Triage Extraction:** Four independent extraction heads — need type, headcount, vulnerability flags, and medical urgency — each with its own confidence score. Not classification: extraction.

**Stage 3 — Confidence Calibration:** Isotonic Regression per head maps raw overconfident scores to observed correctness rates. After calibration, "0.7 confidence" means right about 70% of the time. Produces a **(lower, point, upper)** headcount interval used directly by the solver.

**Stage 4 — Geo-Resolution Cascade:** Six-step ordered cascade (GPS → text coordinates → Nominatim → landmark gazetteer → cell region → unknown). Resolution is **never upgraded** to make a map look better — a ward-level demand renders as a hex, never as a pin. *A pin is a promise.*

**Stage 5 — Deduplication:** Four hard gates must all pass to merge two messages (spatial radius, need type agreement, headcount ratio ≤ 1.6×, neither unlocatable). Default: gated union-find with H3 spatial blocking and anti-chaining centroid refinement. Optional: HDBSCAN + FAISS for density-based clustering over LaBSE embeddings.

**Stage 6 — Trust Scoring:** Five-component weighted composite (corroboration 0.28, freshness 0.22, diversity 0.24, consistency 0.18, propagation 0.08). Output is a **continuous score (0–1)** that enters the optimizer's objective — never a binary filter. A hoax at trust 0.15 contributes 15% of its apparent value and loses to any real demand nearby. **Suppressed, not deleted.**

### 2. Allocation Engine

Takes `DemandRecord` objects + fleet + road network → produces a `Plan` with justified `Assignment` objects.

**Solver: Google OR-Tools CP-SAT**

Decision variables: `x[demand, asset]` (rescue) and `y[demand, verifier]` (verification). Each demand gets at most one action.

Objective function:
```
value(d, a) = urgency_weight × need_weight × (1 + vulnerability_bonus)
            × people_lower × trust_score × escalation_weight × equity_multiplier
            − 0.15 × travel_minutes
```

**The two lines that define the confidence interval idea:**
- Capacity is planned against `people_upper` — never arrive with too few seats
- Value is credited against `people_lower` — never over-credit a guess

An uncertain demand costs the same to serve but earns less, so the solver **naturally prefers confirmed demand** without any explicit rule.

**Six novelty flags** (each is one row of the ablation table):

| Flag | What It Does |
|---|---|
| `use_confidence` | Headcount enters as an interval, not a point |
| `use_reserve` | Hold capacity back under uncertainty |
| `use_verification` | Uncertainty routes to verification dispatch |
| `use_trust` | Low trust suppresses asset commitment |
| `use_equity` | Per-zone deficit multiplier for fairness |
| `use_escalation` | Aging demand rises in the ordering |

**Graceful degradation:** When mean intake confidence drops below 0.45, the system switches to `DECISION_SUPPORT` mode and stops auto-assigning. *When the system loses confidence, it stops guessing.*

**Justification Engine:** Every assignment carries machine-readable reasons: urgency, headcount interval, vulnerability, trust, reachability, location quality, zone equity, and alternatives rejected. Unserved demands also get explanations — silence about a demand nobody is coming for is how people get missed.

---

## Quick Start

**Requirements:** Python 3.11+, `uv`, Node.js / npm

```bash
# Clone and install
git clone <repo>
cd PHAROS
uv sync

# Install console dependencies
cd web/console && npm install && cd ../..

# Run the full demo (API on :8000, Console on :5173)
make demo
```

Everything runs on a laptop, **offline, no containers required**.

### All Commands

```bash
make demo       # API on :8000, Console on :5173
make api        # API only
make console    # Console only

make ablate     # Full ablation table, 3 seeds
make dedupe     # Naive vs. deduplicated demand comparison
make load       # 40,000-message throughput test

make test       # pytest
make lint       # ruff
```

### Optional: Neural Path

For cross-lingual embeddings using LaBSE (requires ~1.8 GB download):

```bash
pip install pharos-sensing[neural]
PHAROS_EMBEDDER=labse make demo
```

### Optional: Self-Hosted Geocoder

```bash
make up-geo     # Starts Nominatim container via Docker Compose
```

---

## Demo Scenario: Kerala Flood

Defined in `services/simulator/scenarios/kerala_flood_demo.yaml`:

| Parameter | Value |
|---|---|
| Region | Ernakulam district, Kerala (9.93°N, 76.27°E), 25 km radius |
| Duration | 6 hours |
| Messages | ~6,000 from ~1,700 real emergencies |
| Fleet | 60 boats, 20 ambulances, 45 trucks, 8 operators, 14 volunteers |
| Road degradation | 15% flooded at 1.5h, 30% at 3h |
| Replan interval | Every 15 minutes |
| Duplicate rate | 25% |
| Language mix | 45% English, 25% Hindi, 30% code-mixed |
| Hoax rate | 3% |

---

## Evaluation Framework

### Ablation Table

`make ablate` runs every configuration across 3 seeds and reports mean ± spread. A single-seed result is not a result.

| Configuration | Description |
|---|---|
| FIFO | Baseline: first-in-first-served |
| Nearest | Baseline: nearest asset to each demand |
| Full PHAROS | All six flags enabled |
| no_dedup | Deduplication disabled |
| no_calibration | Raw headcount scores, no isotonic regression |
| no_confidence | Point estimate instead of interval |
| no_verification | No verification dispatch |
| no_trust | Trust suppression disabled |
| no_equity | Pure throughput, no fairness weighting |

### Metrics

**Operational:** Raw coverage, coverage within urgency window, worst-off zone coverage, zone Gini, median time-to-reach, P95 time to first assignment, wasted effort (hoax / duplicate / stale sorties).

**Model:** Dedup pairwise precision/recall, geo accuracy by resolution level, extraction accuracy per confidence bucket, calibration ECE and Brier score.

**System:** Throughput (messages/sec), solve time per replan.

### Red Team Attacks

Three attack types modelled on documented incidents:

| Attack | Real-World Source |
|---|---|
| Hoax Cluster | Kerala 2018 fabricated dam alerts — 40 messages from 2 accounts in 4 minutes |
| Amplification Cascade | 2021 India COVID stale leads — a resolved case re-shared 25 times |
| Stale Reports | 2021 oxygen/bed lead circulation — genuine emergencies hours after resolution |

---

## Operator Console

React 18 + TypeScript + Vite single-page application with:

- **Interactive Map** (MapLibre GL): Demands as pins (only if point/building resolution), hex zones, road network, asset routes, river overlay
- **Demand Queue**: Filterable, sortable with confidence/trust indicators
- **Detail Panel**: Full demand record with raw citizen texts, assignment trace with justification, alternatives considered
- **Equity Slider**: Real-time efficiency ↔ equity trade-off, re-solves instantly
- **Controls**: Play/Step, Break Bridge, Inject Hoax, Drop Confidence, Reset
- **Metrics Dashboard**: Live coverage, waste, dedup, calibration stats
- **WebSocket**: Real-time push updates on every replan

---

## API Reference

The FastAPI server exposes HTTP REST + WebSocket at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

Key endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Session phase, clock, mode, banner |
| `/api/demands` | GET | Filterable demand list |
| `/api/plan` | GET | Current plan with justifications |
| `/api/metrics` | GET | Live operational metrics |
| `/api/control/tick` | POST | Advance scenario clock |
| `/api/control/equity` | POST | Set equity slider (0–1) |
| `/api/control/break-bridge` | POST | Collapse a river crossing |
| `/api/control/redteam` | POST | Inject hoax/amplification/stale attack |
| `/api/control/override` | POST | Manual operator reassignment |
| `/ws` | WebSocket | Push replan results to console |

Every action is written to an immutable audit trail (SQLite).

---

## Key Design Principles

1. **Uncertainty is first-class** — Headcounts are intervals, confidence is calibrated, trust is continuous. The system hedges rather than guessing.

2. **Suppression over deletion** — Hoaxes are suppressed (trust 0.15 → 15% value), never deleted. A hoax is a resource contention problem, not a moderation problem.

3. **Visual honesty** — A ward-level location renders as a hex, never as a pin. *A pin is a promise.* This directly addresses the Kerala 2018 supply-drop failure.

4. **Every decision is justified** — Assignments carry reasons including alternatives rejected. Unserved demands carry explanations. Silence is how people get missed.

5. **Operator authority** — The equity slider, manual overrides, and decision-support mode ensure the operator owns the trade-offs. An automated decision an operator cannot override is not decision support.

6. **Measured, not asserted** — Every novelty claim is a flag that can be toggled off. The ablation table proves each claim against baselines with multiple seeds. *"Compared to what?" has an answer.*

7. **Graceful degradation** — When sensing confidence collapses, the system stops assigning and says so. It states its own limits rather than guessing.

---

## Dependencies

**Core Python packages:**

```
pydantic >= 2.0        ortools >= 9.10      networkx >= 3.2
numpy >= 1.26          scikit-learn >= 1.5  h3 >= 4.1
fastapi >= 0.115       uvicorn              sqlalchemy >= 2.0
websockets             pyyaml
```

**Optional neural path** (`pip install pharos-sensing[neural]`):

```
sentence-transformers >= 3.0    torch >= 2.2
faiss-cpu >= 1.8                hdbscan >= 0.8
```

**Frontend:** React 18, MapLibre GL, Recharts, TanStack React Query, TypeScript, Vite

---

## Project Structure Reference

| Path | Description |
|---|---|
| `packages/pharos-core/` | Shared Pydantic data models (`MessageEnvelope`, `DemandRecord`, `Plan`) |
| `services/sensing/` | Full 6-stage sensing pipeline |
| `services/allocator/` | CP-SAT solver, cost matrix, justification engine |
| `services/simulator/` | Scenario generator, corpus, red team, evaluation harness |
| `services/api/` | FastAPI server, WebSocket, session, audit |
| `web/console/` | Operator dashboard |
| `scripts/` | Diagnostic and tuning utilities |
| `services/simulator/scenarios/kerala_flood_demo.yaml` | Reference disaster scenario |

---

## Documentation

| File | Contents |
|---|---|
| [`PROJECT_OVERVIEW.md`](./PROJECT_OVERVIEW.md) | Full system description with design rationale |
| [`WORKFLOW.md`](./WORKFLOW.md) | End-to-end flow with exact formulas and models |
| [`docs/DEMO.md`](./docs/DEMO.md) | Demo walkthrough and operator guide |
| [`PRESENTATION.md`](./PRESENTATION.md) | Slide-by-slide narrative for presentations |
