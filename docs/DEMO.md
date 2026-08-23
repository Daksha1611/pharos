# Running the demo

```bash
make demo
```

Two processes, no containers, no network. Open **http://localhost:5173**.

First load takes about 30 seconds: it generates 5,500 messages from 1,700 real
events and runs every one of them through intake. The console shows progress.
After that everything is in memory and instant.

If `make demo` is unavailable, run the two halves separately:

```bash
make api        # :8000
make console    # :5173
```

---

## The six-minute script

| Time | Beat | What to do | What to say |
|---|---|---|---|
| 0:00 | The problem | Press **Play**. Watch the clock and the message counter climb. | *"Forty thousand messages, six hours, and a fleet that can reach a fraction of them. Which ones need a boat in the next fifteen minutes?"* |
| 0:45 | Deduplication | Point at the bottom strip: **messages in** vs **demand records** vs **duplicates removed**. | *"Kerala 2018 ran at 25% duplicates and found out mid-crisis. Every duplicate here is a boat that would have gone to a house someone else was already reaching."* |
| 1:15 | Location honesty | Open the legend, top left of the map. Click the **Not located** filter in the queue. | *"A third of intake resolves to nothing better than a district centroid. We list those. We never draw them as a pin, because a pin is a promise. That is the documented Kerala supply-drop failure, and here it is a rendering rule."* |
| 1:45 | The seam | Click any demand. Point at the headcount interval and the confidence bars. | *"Not seven people — five to twelve, at 0.62 confidence. The solver commits twelve seats and credits itself five. Plan for the worst case, count value for the best-confirmed case. That is where we differ."* |
| 2:30 | Justification | Scroll the detail panel to the assignment trace. | *"Every assignment carries why — including what was rejected. truck-38 was closer and was out of capacity."* |
| 3:15 | Equity | Drag the **Efficiency ↔ Equity** slider to 1.0. Toggle **Equity view**. | *"The operator owns this trade-off, not us. Watch who starts getting served and who now waits."* |
| 4:00 | Misinformation | Press **Inject hoax**. Find the new cluster — 40 messages, 2 accounts, four minutes. | *"Trust drops, so it contributes a fraction of its apparent value and loses to any real demand nearby. It is still on screen. We suppress, we do not delete — a hoax is resource contention, not a moderation problem."* |
| 4:45 | Hazard | Press **Break bridge**. | *"One river crossing gone. Boats can still cross flooded roads; trucks cannot. The plan re-solves around it in under a second."* |
| 5:15 | Numbers | The output of `make ablate`, or the table in `docs/RESULTS.md`. | *"Two baselines, five ablations, three seeds. Each row removed is one claim, quantified."* |
| 5:45 | **Close here** | Press **Drop confidence**. | *"When the sensing layer loses confidence across the board, the system stops assigning and hands control back. It does not guess. That is the answer to 'what if your model is wrong.'"* |

Close on the banner, not on a green dashboard. A system that states its own
limits is what a domain judge remembers.

---

## What each control actually does

None of these are canned animations. Every one exercises the real code path.

| Control | What happens |
|---|---|
| **Step / Play** | Advances the scenario clock. Assets that finished a sortie return to depot, new reports arrive, unresolved demands escalate, the solver re-runs. |
| **Equity slider** | Changes the objective's per-zone deficit multiplier and re-solves. Zones that have been served less get weighted up. |
| **Break bridge** | Disables a real edge in the road graph, invalidates the route cache, re-solves. Reachability genuinely changes. |
| **Inject hoax** | Pushes 40 fabricated messages from 2 accounts through the same normalize → extract → resolve → trust path as everything else. Nothing is special-cased. |
| **Drop confidence** | Caps intake confidence below the global floor. The solver refuses to auto-assign and returns a plan in decision-support mode. |
| **Reset** | Clock back to zero, roads restored, assets home. The scenario is not regenerated. |

---

## Before you present

- Run the script five times on the actual demo laptop, **with wifi off**.
- Let the first load finish before you start talking; it happens once per boot.
- The road graph is cached in `data/road_graph.pkl` after the first build, so
  subsequent starts are faster.
- **Reset** puts the clock back without reloading the scenario. Use it between
  rehearsals.

## If something goes wrong

| Symptom | Fix |
|---|---|
| Console stuck on the loading bar | The API is still sensing — about 25 seconds. Check the `make api` output. |
| Map is black with no roads | The API is not reachable. The Vite proxy expects it on :8000. |
| Plan shows `EMPTY` | Clock is at zero and no messages have arrived yet. Press **Step** a few times, or **Play**. |
| Everything committed, nothing new assigned | Normal late in the scenario — the fleet is saturated. Press **Reset**. |
| A control returns 503 | The session is still loading or failed. `/api/status` carries the reason. |
