# PHAROS: Complete System Workflow

*End-to-end flow from citizen distress message to verified rescue, with the exact formulas and models used at each stage.*

---

## System Flow Diagram

```
CITIZEN MESSAGES (WhatsApp, SMS, Twitter, Calls, Web Forms, Control Room)
         │
         ▼
┌─── SENSING PIPELINE ──────────────────────────────────────────┐
│  Normalize → Extract → Calibrate → Geo-Resolve → Dedupe → Trust │
└───────────────────────────┬────────────────────────────────────┘
                            │
                      DemandRecord (The Seam)
                            │
                            ▼
┌─── ALLOCATION ENGINE ─────────────────────────────────────────┐
│  Road Network → Cost Matrix → CP-SAT Solver → Justification   │
└───────────────────────────┬────────────────────────────────────┘
                            │
                       Plan + Assignments
                            │
                            ▼
┌─── OPERATOR CONSOLE ──────────────────────────────────────────┐
│  Map + Demand Queue + Equity Slider + Override Controls        │
└───────────────────────────┬────────────────────────────────────┘
                            │
                            ▼
                 DISPATCH → VERIFY → REPLAN (loop)
```

---

## Phase 1: Data Intake

**Sources:** WhatsApp Business API, SMS gateways, Twitter/X scrapers, phone call transcripts, web forms (like keralarescue.in), and manual control-room entries.

Each message arrives as a `MessageEnvelope`:
```
MessageEnvelope:
  message_id      → "MSG-0000047"
  channel         → chat | social | sms | web_form | call_transcript | control_room
  raw_text        → "pls hlp, watr rising near Thrikkakra temple, 7 ppl trapped, ek baby bhi hai"
  sender_hash     → SHA-256 hash (raw identity never leaves intake)
  received_at     → timestamp
  attached_geo    → {lat, lon, accuracy_m}  (only ~35% of messages have this)
  channel_metadata → {sender_region, language hint, ...}
```

---

## Phase 2: Sensing Pipeline

### Stage 2.1: Text Normalization

**Model/Tech:** SymSpell algorithm (delete-based edit distance) + lexicon-based language detection.

**Language Detection** — Scores text against curated function-word sets:
```
HI_MARKERS = {"hai", "hain", "ka", "ke", "ko", "me", "se", "par", "nahi", ...}
EN_MARKERS = {"the", "is", "are", "we", "our", "need", "please", "help", ...}

hi_score = count(words ∩ HI_MARKERS) / total_words
en_score = count(words ∩ EN_MARKERS) / total_words

if hi_score > 0.25 and en_score > 0.25 → "mixed"
elif hi_score > en_score                → "hi"
else                                    → "en"
```

**Typo Repair** — SymSpell delete index:
- Precompute single-character deletions of a ~2000 word domain vocabulary
- For each input word, generate its deletions → lookup in the index → O(1)
- Gazetteer place names are added to the vocabulary so "Vaikom" is never "corrected"

**SMS Expansion:**
```
"pls" → "please", "hlp" → "help", "watr" → "water", "ppl" → "people",
"urgnt" → "urgent", "immdtly" → "immediately", "hosp" → "hospital"
```

---

### Stage 2.2: Triage Extraction

**Model/Tech:** Weighted regex cue matching (4 independent extraction heads).

#### Need Type Extraction

Each need type has a bank of weighted regex cues. All cues are tested; scores accumulate per type.

```
Example cue weights for EVACUATION:
  "boat" | "naav"           → weight 3.0
  "rescue" | "evacuat"      → weight 3.0
  "trapped" | "fase"        → weight 2.5
  "submerged" | "chest deep" → weight 2.0
  "SOS"                     → weight 1.2

Score per type = sum of matched cue weights
```

**Need Type Confidence Formula:**
```
total    = sum of ALL matched scores across ALL types
winner   = type with highest score
best     = winner's score
second   = runner-up's score (0 if only one matched)

share    = best / total                         (how dominant is the winner)
margin   = (best - second) / best               (how far ahead of runner-up)
strength = min(1.0, best / 6.0)                 (absolute evidence mass)

need_type_raw = 0.40 × share + 0.35 × margin + 0.25 × strength
```

This is a RAW score — systematically overconfident. Calibration fixes it in Stage 2.3.

#### Headcount Extraction

Hierarchical pattern matching — tries methods in order, stops at the first hit:

| Priority | Pattern | Example | Confidence |
|---|---|---|---|
| 1 | First-person: "we are {N}" / "hum {N}" | "we are 7" → 7 | 0.93 |
| 2 | Number + person unit: "{N} people/log" | "7 people trapped" → 7 | 0.85 |
| 3 | Number + household unit × 4.6 | "2 families" → 9 | 0.55 |
| 4 | Bare number (largest in text) | "send help 7" → 7 | 0.30 |
| 5 | Household prior (no number found) | (nothing) → 5 | 0.15 |

**The 4.6 multiplier** comes from the Kerala Census mean household size.

#### Vulnerability Extraction

Regex cue detection in English and Hindi:
```
"infant":   r"\b(baby|infant|newborn|bacha|bache|toddler)\b"
"elderly":  r"\b(elderly|old (man|woman|people)|budhe|senior citizen)\b"
"pregnant": r"\b(pregnant|garbhvati|expecting mother)\b"
"disabled": r"\b(disabled|cannot walk|chal nahi sakta|wheelchair)\b"
"injured":  r"\b(injured|ghayal|wounded|bleeding|fracture)\b"
```

#### Medical Urgency Extraction

Three tiers, highest match wins:
```
CRITICAL (weight 3.0): unconscious | behosh | bleeding heavily | cardiac | dialysis | oxygen
MODERATE (weight 2.0): injured | ghayal | fracture | insulin | high fever | severe
MILD     (weight 1.0): sick | bimar | fever | unwell | weak | medicine | dawai
```

---

### Stage 2.3: Confidence Calibration

**Model/Tech:** Scikit-learn `IsotonicRegression` (per extraction head).

**Why:** Raw extraction scores are overconfident (like raw softmax). The extractor says "0.99 confidence" on nearly everything it matches. That's useless for a solver deciding whether to commit a boat.

**How Isotonic Regression works:**
```
Training data: pairs of (raw_score, was_it_correct)
  e.g., [(0.92, True), (0.88, False), (0.95, True), (0.45, False), ...]

IsotonicRegression.fit(raw_scores, correct_labels)
  → Learns a monotonic step function mapping raw → calibrated

After fitting:
  raw 0.92 → calibrated 0.78  (meaning: "correct about 78% of the time")
  raw 0.45 → calibrated 0.31  (meaning: "correct about 31% of the time")
```

**Bounds:** Clamped to [0.02, 0.98] — never claims certainty, never claims impossibility.

**Fallback** (if < 40 training samples for a head):
```
calibrated = clip(0.5 + 0.6 × (raw - 0.5), 0.05, 0.95)
```
This shrinks toward 0.5 (uncertain) so an uncalibrated head never pretends to be confident.

**Validation Metrics:**
- **ECE (Expected Calibration Error):** Average |predicted probability - observed frequency| across bins
- **Brier Score:** Mean squared error between predicted probability and actual outcome

#### Quantity Interval (from calibrated confidence)

```
point = extracted headcount (e.g., 7)
confidence = calibrated score (e.g., 0.78)

lower = round(point × confidence)       = round(7 × 0.78) = 5
upper = round(point / confidence)       = round(7 / 0.78) = 9

Result: quantity_interval = (lower: 5, point: 7, upper: 9)
```

- **Solver plans capacity against `upper`** — never arrive with too few seats
- **Solver credits value against `lower`** — never over-count a guess

---

### Stage 2.4: Geo-Resolution Cascade

**Model/Tech:** Ordered cascade (6 steps) + local landmark gazetteer (token-inverted index) + Uber H3 hexagonal spatial index.

Tries each method in order, **stops at the first hit**:

| Step | Method | Tech Used | Resolution Level | Confidence |
|---|---|---|---|---|
| 1 | Channel-attached GPS | Raw coordinates from phone | point/building/street/ward | 0.28–0.95 (based on accuracy_m) |
| 2 | Coordinates in text | Regex: `r"(\d{1,3}\.\d{3,7})[,\s]+(\d{1,3}\.\d{3,7})"` | point | 0.92 |
| 3 | Nominatim geocoder | Self-hosted OpenStreetMap geocoder (optional) | building | 0.80 |
| 4 | Landmark gazetteer | Token-inverted index over 900 local landmarks | street | 0.65 |
| 5 | Sender cell region | Cell tower metadata from SMS/call channel | ward | 0.35 |
| 6 | Nothing resolved | — | unknown | 0.0 |

**Landmark Gazetteer** — How it works:
```
900 landmarks generated deterministically for Ernakulam district:
  Types: panchayat offices, temples, mosques, churches, ferry jetties,
         mills, bus stands, markets, schools, hospitals, etc.

Each landmark has aliases in English, Malayalam, and Hindi:
  e.g., "Thrikkakara Panchayat Office" has aliases:
    "thrikkakara panchayat", "thrikkakara office", "thrikkakara panchayat office"

Token-inverted index:
  "thrikkakara" → [landmark_42, landmark_43, ...]
  "panchayat"   → [landmark_42, landmark_108, ...]
  "temple"      → [landmark_17, landmark_55, ...]

Matching: tokenize input text → lookup each token → intersect candidate lists
  → Score by fraction of landmark name tokens matched
  → Best match above threshold wins
```

**Resolution confidence from GPS accuracy:**
```
if accuracy_m ≤ 50    → "point"    (confidence 0.95)
if accuracy_m ≤ 200   → "building" (confidence 0.80)
if accuracy_m ≤ 1000  → "street"   (confidence 0.55)
if accuracy_m ≤ 3000  → "ward"     (confidence 0.28)
```

**Key rule:** Resolution is NEVER upgraded. A ward-level demand renders as a hex zone on the map, not a pin. *A pin is a promise.*

---

### Stage 2.5: Deduplication / Clustering

**Model/Tech:** HDBSCAN (density-based clustering) + FAISS (approximate nearest-neighbor) OR union-find with centroid refinement. H3 spatial blocking.

#### Embedding (two backends)

**Default — Hashing Embedder (offline, deterministic):**
```
For each message, produce a 512-dim vector:
  Lexical half (256-dim):  hashed character n-grams (3,4,5-grams)
  Semantic half (256-dim): need_type one-hot (8 dims)
                         + vulnerability flags (5 dims)
                         + urgency level (4 dims)
                         + log-bucket of headcount (6 dims)
                         + zero-padded to 256

The semantic half is why it works cross-lingually:
  Hindi: "7 log fase hain, boat chahiye"  → EVACUATION, 7 people
  English: "7 people trapped, need boat"   → EVACUATION, 7 people
  → Same semantic frame → same semantic embedding half
```

**Optional — LaBSE Embedder (neural):**
```
sentence-transformers/LaBSE model → 768-dim embedding
FAISS index for approximate nearest-neighbor search
HDBSCAN for density-based clustering
```

#### Four Hard Gates (ALL must pass to merge)

```
Gate 1 — Spatial:
  base_tolerance = 180m
  effective_radius = base + msg_A.positional_uncertainty + msg_B.positional_uncertainty
  if haversine(A, B) > min(effective_radius, 3000m) → REJECT

Gate 2 — Need type:
  if A.need_type ≠ B.need_type → REJECT

Gate 3 — Headcount:
  ratio = max(A.people, B.people) / max(1, min(A.people, B.people))
  if ratio > 1.6 → REJECT

Gate 4 — Unlocatable:
  if A.resolution == "unknown" OR B.resolution == "unknown" → REJECT
  (Never merge on a coordinate we invented)
```

#### Anti-Chaining Refinement
```
After initial clusters (connected components / HDBSCAN):
  For each cluster, compute centroid embedding
  For each member, check similarity to centroid
  If similarity < 0.68 → remove from cluster, create separate demand

This prevents transitive drift:
  A~B (similar) and B~C (similar) does NOT mean A~C
```

**Threshold:** 0.68 similarity — chosen by sweeping against ground truth. Holds pairwise precision at 0.84.

**Output:** `duplicate_collapse_count` = number of raw messages merged into this demand.

---

### Stage 2.6: Trust Scoring

**Model/Tech:** Weighted composite of 5 hand-engineered components.

#### Master Formula
```
trust_score = 0.28 × corroboration
            + 0.24 × diversity
            + 0.18 × consistency
            + 0.22 × freshness
            + 0.08 × propagation
```

#### Component 1: Corroboration (weight 0.28)
```
corroboration = min(1.0, distinct_senders / 3.0)

Counts VOICES, not messages.
One person posting 8 times = 1 voice.
3 independent reporters = corroboration of 1.0 (saturated).
```

#### Component 2: Diversity (weight 0.24)
```
channel_entropy = -Σ (pᵢ × log(pᵢ)) / log(k)
  where pᵢ = fraction of reports from channel i, k = number of channels

sender_entropy = -Σ (pⱼ × log(pⱼ)) / log(m)
  where pⱼ = fraction of reports from sender j, m = number of senders

channel_ceiling = min(1.0, num_channels / 3.0)
diversity = min(channel_ceiling, 0.45 × channel_entropy + 0.55 × sender_entropy)

Example:
  10 WhatsApp messages from 1 group → 1 channel, 1 effective voice → diversity ≈ 0.0
  3 messages from SMS + Twitter + WhatsApp → 3 channels → diversity ≈ 0.85
```

#### Component 3: Consistency (weight 0.18)
```
type_agreement = count(most_common_need_type) / total_reports
  e.g., 4 say "evacuation", 1 says "medical" → agreement = 0.8

headcount_spread:
  cv = (max_count - min_count) / mean_count
  spread = max(0.0, 1.0 - min(1.0, cv / 2.5))

consistency = 0.7 × type_agreement + 0.3 × spread

If type_agreement < 0.7 → flag: "members disagree on need type"
```

#### Component 4: Freshness (weight 0.22)
```
freshness = 0.5 ^ (staleness_minutes / 90.0)

90-minute half-life:
  0 min  → freshness = 1.0   (100%)
  90 min → freshness = 0.5   (50%)
  180 min → freshness = 0.25  (25%)
  270 min → freshness = 0.125 (12.5%)

This is the fix for the 2021 stale-lead problem:
  Oxygen/bed leads circulated for hours after the resource was gone.
  With freshness decay, they quietly stop competing for assets.
```

#### Component 5: Propagation (weight 0.08)
```
per_sender = message_count / distinct_senders
rate = message_count / time_span_minutes

penalty = 0.0
if per_sender ≥ 3.0:
  penalty += min(0.55, 0.16 × (per_sender - 2.0))
if rate > 0.5 msgs/min AND distinct_senders ≤ 2:
  penalty += 0.25

propagation = max(0.05, 1.0 - penalty)

Example hoax signature:
  40 messages from 2 accounts in 4 minutes
  per_sender = 20, rate = 10/min
  penalty = min(0.55, 0.16 × 18) + 0.25 = 0.55 + 0.25 = 0.80
  propagation = max(0.05, 0.20) = 0.20
```

#### Single-Report Floor
```
if distinct_senders == 1 AND propagation > 0.6:
  trust_score = max(raw_score, 0.52 × freshness)

Most real emergencies are reported once. A lone report is not a red flag.
```

---

## Phase 3: The Seam — DemandRecord

The output of sensing, the input to allocation. Five novel fields:

```
DemandRecord:
  demand_id                → "D-000142"
  need_type                → EVACUATION
  quantity_interval         → (lower: 5, point: 7, upper: 9)
  quantity_confidence       → 0.78 (calibrated)
  trust_score              → 0.83
  location                 → (lat, lon, resolution: "street", method: "gazetteer")
  vulnerability_flags      → ["infant"]
  medical_urgency          → NONE
  duplicate_collapse_count → 4
  source_messages          → [MSG-0001, MSG-0047, MSG-0112, MSG-0389]
```

---

## Phase 4: Allocation Engine

### 4.1: Road Network

**Model/Tech:** NetworkX graph + OSMnx (OpenStreetMap) + Dijkstra shortest path.

```
Graph:
  Nodes = road intersections
  Edges = road segments, weighted by travel time

Road degradation (live updates):
  Flooded edge:    trucks/ambulances BLOCKED, boats cross at 9 km/h
  Collapsed bridge: NOTHING crosses (not even boats)

Example: At hour 1.5, 15% of roads flood. At hour 3.0, 30% flood.
NDRF can clear paths → edges re-enabled → cost matrix invalidated → replan.
```

### 4.2: Cost Matrix

**Model/Tech:** Dijkstra shortest path (one run per unique asset-type + depot-node pair).

```
For each (asset, demand):
  cost = dijkstra_shortest_path_time(asset.depot, demand.location)
  
  Boats: can cross flooded edges (at 9 km/h penalty)
  Trucks: cannot cross flooded edges (infinite cost)
  Verification assets: flat 3.0 minutes (phone call is location-independent)

RouteOracle: caches results, invalidated only when road state changes.
Top-K pruning: keep nearest 10 assets per demand (limits model to ~7,000 variables).
```

### 4.3: CP-SAT Optimizer

**Model/Tech:** Google OR-Tools CP-SAT (Constraint Programming with Satisfiability).

#### Decision Variables
```
x[d, a] ∈ {0, 1}  — assign physical asset a to demand d for rescue
y[d, v] ∈ {0, 1}  — assign verifier v to demand d for verification
```

#### Constraints
```
1. Exclusivity:  Σₐ x[d,a] + Σᵥ y[d,v] ≤ 1   (each demand: rescue OR verify, not both)
2. Capacity:     Σ_d x[d,a] × d.people_upper ≤ a.capacity   (seats per sortie)
3. Reserve:      Σₐ committed[a] ≤ (1 - reserve_fraction) × total_fleet
                 reserve_fraction = reserve_factor × (1 - mean_confidence)
```

#### Objective Function (Maximize)
```
For each rescue assignment (d, a):
  value(d, a) = urgency_weight(d.medical_urgency)
              × need_weight(d.need_type)
              × (1 + vulnerability_bonus(d))
              × d.people_lower                    ← credited headcount
              × trust_score(d)                    ← hoax suppression
              × escalation_weight(d)              ← aging demands rise
              × equity_multiplier(d.zone)         ← underserved zones boosted
              − 0.15 × travel_minutes(a → d)      ← opportunity cost
```

**Weight tables (from code):**

| Medical Urgency | Weight |
|---|---|
| NONE | 1.0 |
| MILD | 1.4 |
| MODERATE | 2.2 |
| CRITICAL | 4.0 |

| Need Type | Weight |
|---|---|
| Medical | 1.8 |
| Evacuation | 1.6 |
| Missing Person | 1.5 |
| Water | 1.2 |
| Shelter | 1.0 |
| Food | 0.9 |
| Sanitation | 0.7 |
| Infrastructure | 0.6 |

| Vulnerability | Bonus |
|---|---|
| Injured | +0.40 |
| Infant | +0.35 |
| Pregnant | +0.35 |
| Elderly | +0.30 |
| Disabled | +0.30 |
| (max total) | +0.90 |

**For verification assignments (d, v):**
```
verify_value(d, v) = 0.55 × potential_rescue_value(d) × (1 - d.quantity_confidence)
                   − 0.15 × 3.0   (flat 3-min cost)
```

**Graceful Degradation:**
```
if mean(all_demand_confidences) < 0.45:
  mode = DECISION_SUPPORT   ← stop auto-assigning, hand control to human
```

**Performance:** Candidate window = top 700 demands. Top-K = 10 assets per demand. Solves within 10 seconds.

### 4.4: Justification Engine

Every assignment carries machine-readable reasons:
```
Assignment justification:
  ├── Urgency:        "CRITICAL medical, weight 4.0"
  ├── Headcount:      "interval [5, 7, 9], committed 9 seats, credited 5 people"
  ├── Vulnerability:  "infant present, bonus +0.35"
  ├── Trust:          "0.83 (4 reports, 3 channels)"
  ├── Reachability:   "Boat-12, 14 min via Route A (flooded Route B bypassed)"
  ├── Location:       "street-level, method: gazetteer, geo_confidence: 0.65"
  ├── Zone equity:    "Zone H3-8a deficit 0.4, multiplier 1.8"
  └── Alternatives:   "Truck-38 rejected: 12 min but out of capacity"

Unserved demands ALSO get explanations:
  └── "Demand D-000451: unserved — trust 0.31, verification dispatched instead"
```

---

## Phase 5: Dispatch & Execution

```
Plan pushed to operator console via WebSocket:
  ├── Boat-12   → D-000142 (evacuation, 7 people, 14 min ETA)
  ├── NDRF-3    → D-000087 (structural collapse, 12 trapped, 22 min ETA)
  ├── Truck-7   → D-000203 (food for 45, refugee camp, 18 min ETA)
  ├── Ambulance-5 → D-000091 (critical cardiac, 8 min ETA)
  └── Operator-2  → D-000451 (VERIFY: 100 people claimed, 1 report, trust 0.31)

Operator can:
  ├── Approve the plan (auto-dispatch)
  ├── Override an assignment (manual reassign)
  ├── Adjust equity slider (0 = throughput, 1 = fairness) → instant re-solve
  ├── Break a bridge → road graph updates → instant re-solve
  └── Switch to Decision Support mode
```

---

## Phase 6: Verification & Closure

```
For high-uncertainty demands (confidence < 0.55 or trust < 0.40):
  1. Operator/volunteer calls original reporter
  2. Social listening: detect "we are safe" linked to cluster
  3. Drone flyover or field volunteer check

Outcomes:
  VERIFIED  → confidence upgraded, trust boosted → higher priority next replan
  RESOLVED  → demand closed → asset returns to depot → freed for next assignment
  FALSE     → trust dropped to ~0.0 → demand suppressed → asset freed
```

---

## Phase 7: Continuous Replan Loop

```
Every 15 minutes (configurable via replan_minutes in YAML):

  1. New messages arrive → sensing pipeline processes them
  2. Existing demands get new corroboration → trust/confidence updated
  3. Road network changes (new flooding, NDRF clears path, bridge collapse)
  4. Completed sorties → assets return to depots
  5. Unresolved demands escalate (aging → higher urgency weight)
  6. Stale demands decay:
       decayed_trust = current_trust × 0.5^(staleness / 90)
       (floor at 0.05 — never fully deleted)
  7. Solver re-runs with updated state → new plan
  8. Plan pushed to operator console via WebSocket

  If mean_confidence < 0.45 → DECISION_SUPPORT mode
  "When the system loses confidence, it stops guessing."
```
