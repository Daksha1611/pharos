# Pharos: Prioritization and Hazard-Aware Resource Orchestration System

## 1. What is Pharos?

**Pharos** is an intelligent orchestration and dispatch system built for disaster response scenarios (like the 2018 Kerala floods). During a major crisis, emergency operation centers are flooded with thousands of incoming SOS messages across various channels (Twitter, SMS, web forms) while possessing only a fraction of the necessary physical resources (boats, trucks, helicopters) to respond to everyone at once. 

Pharos bridges the gap between raw, chaotic, often unverified distress signals and the physical constraints of emergency response fleets. 
Instead of a simple "first-come-first-serve" queue, Pharos dynamically matches available assets to the most critical, verified, and accessible demands. It actively handles duplicate reports, misinformation (hoaxes), shifting hazard environments (like a bridge collapsing), and operational tradeoffs (efficiency vs. equity).

---

## 2. Full Architecture & Component Breakdown

The project is structured as a monolithic repository (monorepo) using Python for the backend and AI/Solver logic, and React/Vite for the frontend console.

### A. `pharos-core` (The Domain Model)
This package holds the fundamental data structures shared across all services.
- **`envelope.py`**: Defines `MessageEnvelope`. Every raw input (SMS, tweet) is standardized into this format before hitting the sensing pipeline.
- **`plan.py`**: Defines `Plan` and `Assignment`. This represents the output of the solver—what assets are assigned where, and importantly, *why* (`Reason`).
- **`enums.py`**: Shared constants for task types (rescue, verification), statuses, and channels.

### B. `pharos-sensing` (The Intake Pipeline)
This service ingests raw messages and transforms them into consolidated, actionable `DemandRecord`s.
- **`normalize/` (`text.py`, `language.py`)**: Normalizes erratic text (typos, slang) and detects languages. It preserves localized vocabulary (like place names).
- **`triage/` (`extract.py`, `calibration.py`)**: Uses extraction to pull out the *Need Type* (Evacuation, Food, etc.), *Headcount* (how many people), *Vulnerabilities* (infants, elderly), and *Medical Urgency*. The calibrator adjusts confidence levels.
- **`geo/` (`gazetteer.py`, `resolve.py`)**: Resolves locations from text into precise coordinates and H3 geographic hex cells.
- **`dedupe/` (`cluster.py`, `embed.py`)**: Vector embeddings are used to cluster messages that are referring to the same underlying emergency. This prevents dispatching three separate boats to the same house just because three family members tweeted.
- **`trust/` (`score.py`)**: Calculates a trust score. It uses corroboration (multiple independent people reporting the same thing) to increase trust, and handles the degradation of trust over time if a report isn't corroborated.
- **`pipeline.py`**: The main orchestrator that wires normalization → extraction → geo-resolve → dedupe → reconcile → trust.

### C. `pharos-allocator` (The Optimization Engine)
Once demands are sensed and mapped, the allocator uses a Constraint Programming solver (Google OR-Tools CP-SAT) to decide which asset goes where.
- **`solver.py`**: The heart of the system. It formulates a maximization problem: prioritize high-value (critical, high-trust, high-confidence) demands while minimizing travel time and respecting asset capacity constraints. 
- **`costmatrix.py` & `graph.py`**: Manages the travel times and routing between assets and demands. It knows about the road network and can immediately react to physical hazards (e.g., a broken bridge breaking a route).
- **`objective.py` & `zones.py`**: Defines how different factors (time, trust, equity) are weighted in the math.
- **`justify.py`**: Generates a human-readable explanation for every assignment and rejection. If a truck isn't sent to a demand, this module explains why (e.g., "asset was out of capacity" or "was assigned to a higher-priority task").

### D. `pharos-api` (The Backend Service)
A FastAPI application that glues everything together and provides a web interface.
- **`main.py` & `routers/`**: Defines the HTTP API endpoints used by the frontend to fetch the current state, step the clock, and inject events.
- **`session.py`**: Manages the state of an active disaster scenario.

### E. `pharos-sim` (The Simulator)
Used for demonstrating the system and running experiments (ablations) without requiring a live crisis.
- **`harness.py` & `generator.py`**: Runs a virtual clock, generates thousands of realistic distress messages, and simulates fleets of rescue vehicles moving around.
- **`scenarios/`**: YAML files defining the simulation environment (like `kerala_flood_demo.yaml`).

### F. `web/console` (The Operator Dashboard)
A React / TypeScript / Vite application that provides a real-time, interactive map and control panel.
- **`MapView.tsx`**: Renders the geographic state, showing demands, assets, and routes.
- **`DetailPanel.tsx` & `ReallocationCard.tsx`**: Allows the operator to click on an assignment and read exactly why the AI made that decision.
- **Controls**: The UI includes buttons to advance time, adjust the equity slider, inject a hoax, break a bridge, or artificially drop confidence to test how the system reacts.

---

## 3. The End-to-End Workflow

1. **Intake**: A distress signal is generated (or simulated) and arrives as a `MessageEnvelope`.
2. **Sensing & Deduplication**: The message flows through `pharos-sensing`. The text is parsed, the location is mapped to an H3 hex cell, and it is clustered with similar nearby messages. A single `DemandRecord` is reconciled from this cluster.
3. **Triage & Trust Assessment**: Based on how many independent sources corroborate the demand, its `trust_score` and `quantity_confidence` are calculated.
4. **Cost Matrix Calculation**: `pharos-allocator` calculates the distance/time from all available trucks and boats to this new demand, avoiding known hazards (flooded roads).
5. **Optimization Solve**: The CP-SAT solver in `solver.py` runs. It attempts to maximize overall "value" (lives saved, resources delivered) minus "cost" (travel time). 
6. **Execution & Justification**: The solver outputs a `Plan`. Assets are dispatched. The system records an audit trail explaining why Asset A went to Demand B, and why Asset C was held back in reserve.
7. **Frontend Update**: The React dashboard fetches the new state, updating the map and metric counters instantly.

---

## 4. Key Business Logic & Design Philosophies

Pharos is built on several strict operational rules designed to build trust with human dispatchers:

> [!TIP]
> **Planning for the Worst, Counting for the Best**
> When dealing with unverified headcounts (e.g., "send help, 5 to 12 people here"), the system reserves `12` seats on a boat (planning for the worst case to ensure safety) but only rewards the solver with `5` points of objective value (counting only the confirmed minimum). This mathematically forces the system to prefer well-corroborated, highly confident demands over vague guesses, without needing a hard rule.

> [!IMPORTANT]
> **Hoaxes & Misinformation Handling**
> If a malicious actor injects a hoax (e.g., 40 fake messages from 2 accounts), Pharos **does not delete** them. Deleting data destroys trust if the model is wrong. Instead, it assigns them a low trust score (e.g., 0.15). The demand remains on the screen, but it only contributes 15% of its apparent value to the optimization solver. It will naturally lose out to real, corroborated emergencies nearby.

> [!NOTE]
> **Equity vs. Efficiency**
> A purely mathematical solver will often ignore hard-to-reach, isolated areas in favor of dense clusters where it can quickly rack up "saved lives." Pharos implements an **Equity Slider**. If operators slide it up, demands in geographic zones that have historically received less help get their objective value multiplied. The system sacrifices raw throughput to ensure fairness across districts.

> [!WARNING]
> **Graceful Degradation (Dropping Confidence)**
> If the sensing layer loses confidence globally (e.g., the NLP model breaks, or the reports become totally erratic), the system refuses to auto-dispatch. It drops into `DECISION_SUPPORT` mode and hands control back to the human operator, providing recommendations instead of taking autonomous action.

> [!TIP]
> **Justification is First-Class**
> Every single assignment has a trace. An operator can see exactly which other assets were considered and the exact mathematical reason they were rejected (e.g., "Asset 45 was closer but lacked capacity", "Asset 12 was chosen instead").

## Summary
Pharos is not just a routing engine; it is a full **uncertainty-aware orchestration platform**. It accepts that crisis data is messy, duplicate-heavy, and sometimes fake, and uses constraint programming to make the best possible physical decisions while leaving the ultimate tradeoffs (like Equity vs Efficiency) in the hands of the human operator.
