/**
 * Data source: LIVE API or DEMO MODE.
 *
 * DEMO MODE is a safety net, not a shortcut. It serves a snapshot captured from
 * the real endpoints by `scripts/capture_fixtures.py`, so both modes render
 * through exactly the same components against exactly the same schema. If the
 * backend dies thirty seconds before the pitch, one switch keeps the screen
 * alive; and because the fixtures come from the API rather than being written
 * by hand, a schema drift is caught the next time they are captured.
 *
 * The controls still work in DEMO MODE. They mutate the in-memory snapshot -
 * the clock advances, the equity weight changes, a bridge goes down - so the
 * script can be walked end to end with no Python process running at all. What
 * they cannot do is re-solve, so DEMO MODE is honest about being a recording:
 * the banner says so, and nothing claims a fresh solver result.
 */

import type {
  AssetView,
  AuditEntry,
  DemandDetail,
  DemandPage,
  Metrics,
  Plan,
  Roads,
  Scenario,
  Status,
  Suggestion,
  Zone,
} from "./api";
import { api } from "./api";
import raw from "./mock/fixtures.json";

export type Mode = "live" | "demo";

interface Fixtures {
  captured_at: string;
  status: Status;
  scenario: Scenario;
  demands: DemandPage;
  plan: Plan;
  suggestion: Suggestion | null;
  assets: AssetView;
  roads: Roads;
  zones: { zones: Zone[]; count: number };
  metrics: Metrics;
  events: { at_min: number; kind: string; message: string }[];
  audit: AuditEntry[];
  details: Record<string, DemandDetail>;
}

const FIXTURES = raw as unknown as Fixtures;

// Mutable copy, so DEMO MODE controls have somewhere to write.
let demo: Fixtures = structuredClone(FIXTURES);

export function resetDemo(): void {
  demo = structuredClone(FIXTURES);
}

export const capturedAt = FIXTURES.captured_at;

// --------------------------------------------------------------------------

const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms));

/** Rows that pass the query, applied client-side over the snapshot. */
function filterDemands(q: string): DemandPage {
  const p = new URLSearchParams(q);
  const maxConf = Number(p.get("max_confidence") ?? 1);
  const minTrust = Number(p.get("min_trust") ?? 0);
  const status = p.get("status");
  const need = p.get("need");
  const resolution = p.get("resolution");
  const search = (p.get("search") ?? "").toLowerCase();
  const limit = Number(p.get("limit") ?? 250);

  const rows = demo.demands.demands.filter((d) => {
    if (status && d.status !== status) return false;
    if (need && d.need !== need) return false;
    if (resolution && d.location.resolution !== resolution) return false;
    if (d.quantity_confidence > maxConf) return false;
    if (d.trust_score < minTrust) return false;
    if (search && !`${d.demand_id} ${d.preview} ${d.location.method}`.toLowerCase().includes(search))
      return false;
    return true;
  });

  return { ...demo.demands, total: rows.length, demands: rows.slice(0, limit) };
}

// --------------------------------------------------------------------------

export function makeClient(mode: Mode) {
  if (mode === "live") return api;

  return {
    status: async () => (await wait(), demo.status),
    scenario: async () => (await wait(), demo.scenario),
    demands: async (q: string) => (await wait(), filterDemands(q)),
    demand: async (id: string) => {
      await wait();
      const hit = demo.details[id];
      if (hit) return hit;
      // Not every row was captured in full. Synthesise a record from the row
      // rather than throwing, so clicking any pin still opens something.
      const row = demo.demands.demands.find((d) => d.demand_id === id);
      if (!row) throw new Error(`no demand ${id}`);
      return {
        ...row,
        field_confidence: {
          need_type: row.quantity_confidence,
          headcount: row.quantity_confidence,
          vulnerability: 0.6,
          medical_urgency: 0.6,
        },
        sources: [],
        cluster_spread_m: 0,
        needs_disambiguation: row.location.resolution === "unknown",
        assignment: null,
        unserved_reason: null,
        audit: [],
      } as DemandDetail;
    },
    plan: async () => (await wait(), demo.plan),
    suggestion: async () => (await wait(), demo.suggestion),
    assets: async () => (await wait(), demo.assets),
    roads: async () => (await wait(), demo.roads),
    zones: async () => (await wait(), demo.zones),
    metrics: async () => (await wait(), demo.metrics),
    audit: async () => (await wait(), demo.audit),
    events: async () => (await wait(), demo.events),

    // --- controls, against the snapshot ---------------------------------
    tick: async () => {
      await wait(200);
      const step = demo.status.tick_minutes ?? 15;
      demo.status = {
        ...demo.status,
        clock_minutes: Math.min(
          demo.status.horizon_minutes ?? 360,
          (demo.status.clock_minutes ?? 0) + step,
        ),
      };
      demo.metrics = {
        ...demo.metrics,
        clock_minutes: demo.status.clock_minutes ?? 0,
        // The snapshot cannot re-solve, so the counters advance plausibly
        // rather than pretending a solver ran.
        messages_ingested: Math.min(
          demo.metrics.messages_total,
          Math.round(demo.metrics.messages_ingested * 1.28),
        ),
      };
      return demo.status;
    },
    replan: async () => (await wait(300), demo.plan),
    setEquity: async (w: number) => {
      await wait(300);
      demo.status = { ...demo.status, equity_weight: w };
      demo.plan = { ...demo.plan, equity_weight: w };
      return demo.plan;
    },
    breakBridge: async () => {
      await wait(300);
      const standing = demo.roads.bridges.filter((b) => b.standing);
      if (standing.length) standing[0].standing = false;
      demo.roads = {
        ...demo.roads,
        counts: { ...demo.roads.counts, disabled: demo.roads.counts.disabled + 1 },
      };
      demo.events = [
        ...demo.events,
        {
          at_min: demo.status.clock_minutes ?? 0,
          kind: "bridge_collapsed",
          message: "river crossing lost",
        },
      ];
      return { broken: standing[0] ?? null, remaining: standing.length - 1 };
    },
    redteam: async (attack: string) => {
      await wait(300);
      demo.events = [
        ...demo.events,
        {
          at_min: demo.status.clock_minutes ?? 0,
          kind: "redteam",
          message: `${attack}: 40 messages injected from 2 accounts`,
        },
      ];
      return { attack, messages: 40, distinct_senders: 2, claimed_people: 45 };
    },
    confidence: async (cap: number | null) => {
      await wait(300);
      const degraded = cap !== null && cap < 0.45;
      demo.status = {
        ...demo.status,
        mode: degraded ? "decision_support" : "autonomous",
        banner: degraded
          ? `Low confidence across intake (mean ${cap?.toFixed(2)} < 0.45) — manual dispatch required`
          : null,
      };
      demo.plan = {
        ...demo.plan,
        mode: degraded ? "decision_support" : "autonomous",
        banner: demo.status.banner ?? null,
        assignments: degraded ? [] : FIXTURES.plan.assignments,
        counts: degraded
          ? { rescue: 0, verification: 0, unserved: demo.plan.counts.unserved }
          : FIXTURES.plan.counts,
      };
      return demo.status;
    },
    reset: async () => {
      await wait(200);
      resetDemo();
      return demo.status;
    },
  };
}

export type Client = ReturnType<typeof makeClient>;
