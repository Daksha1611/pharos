/**
 * API client and shared types.
 *
 * Everything the console shows comes from these endpoints. Nothing is computed
 * in the browser that the backend could be asked for, so the screen and the
 * evaluation harness can never disagree about a number.
 */

export type Phase = "idle" | "loading" | "ready" | "error";

export interface Status {
  phase: Phase;
  detail: string;
  progress: number;
  clock_minutes?: number;
  horizon_minutes?: number;
  clock_iso?: string;
  tick_minutes?: number;
  equity_weight?: number;
  mode?: "autonomous" | "decision_support";
  banner?: string | null;
}

export interface Scenario {
  name: string;
  seed: number;
  centre: [number, number];
  radius_km: number;
  duration_hours: number;
  replan_minutes: number;
  messages_total: number;
  true_events: number;
  demand_records: number;
  gazetteer_entries: number;
  sensing_seconds: number;
  duplicate_rate: number;
  hoax_rate: number;
  language_mix: Record<string, number>;
  assets: Record<string, number>;
  t0: string;
}

/** How honestly we can draw this demand. The map obeys it. */
export type RenderAs = "pin" | "circle" | "hex" | "list_only";

export interface DemandLocation {
  lat: number;
  lon: number;
  resolution: "point" | "building" | "street" | "ward" | "unknown";
  geo_confidence: number;
  method: string;
  h3_cell: string | null;
  render_as: RenderAs;
}

export interface Demand {
  demand_id: string;
  status: string;
  need: string;
  urgency: "none" | "mild" | "moderate" | "critical";
  vulnerability: string[];
  people: number;
  people_lower: number;
  people_upper: number;
  quantity_confidence: number;
  trust_score: number;
  duplicate_collapse_count: number;
  channels: string[];
  escalation_weight: number;
  time_decay: string;
  first_reported_at: string;
  last_corroborated_at: string;
  staleness_minutes: number;
  location: DemandLocation;
  priority: number;
  assigned_asset: string | null;
  assignment_kind: string | null;
  preview: string;
}

export interface DemandPage {
  total: number;
  total_unfiltered: number;
  offset: number;
  counts: {
    by_status: Record<string, number>;
    by_need: Record<string, number>;
    by_resolution: Record<string, number>;
    low_confidence: number;
    low_trust: number;
    unlocatable: number;
    stale: number;
  };
  demands: Demand[];
}

export interface SourceMessage {
  message_id: string;
  channel: string;
  raw_text: string;
  normalized_text: string | null;
  language: string | null;
  language_confidence: number | null;
  received_at: string;
  sender: string;
  had_coordinates: boolean;
  resolved_by: string;
  resolution: string;
  extracted: {
    need: string;
    people: number;
    people_method: string;
    urgency: string;
    vulnerability: string[];
  };
}

export interface Reason {
  factor: string;
  value: string;
  contribution: number | null;
}

export interface Assignment {
  assignment_id: string;
  asset_id: string;
  demand_id: string;
  kind: "rescue" | "verification";
  zone: string | null;
  travel_minutes: number;
  people_committed: number;
  objective_value: number;
  route: [number, number][];
  reasons: Reason[];
}

export interface DemandDetail extends Demand {
  field_confidence: {
    need_type: number;
    headcount: number;
    vulnerability: number;
    medical_urgency: number;
  };
  sources: SourceMessage[];
  cluster_spread_m: number;
  needs_disambiguation: boolean;
  assignment: Assignment | null;
  unserved_reason: string | null;
  audit: { at: string; actor: string; action: string; evidence: unknown }[];
}

export interface Plan {
  plan_id: string | null;
  created_at?: string;
  mode: "autonomous" | "decision_support";
  banner: string | null;
  equity_weight: number;
  solver_status: string;
  solve_time_ms: number;
  objective_value: number;
  reserve: {
    assets_held: number;
    total_assets: number;
    mean_confidence: number;
    rationale: string;
  } | null;
  assignments: Assignment[];
  counts: { rescue: number; verification: number; unserved: number };
  unserved: {
    demand_id: string;
    explanation: string;
    nearest_asset_id: string | null;
    nearest_travel_minutes: number | null;
  }[];
}

export interface Asset {
  asset_id: string;
  type: string;
  capacity: number;
  speed_kmh: number;
  state: string;
  lat: number;
  lon: number;
  depot_id: string;
  is_verifier: boolean;
  serves: string[];
  job: {
    demand_id: string;
    kind: string;
    people_committed: number;
    eta_minutes: number;
    free_in_minutes: number;
  } | null;
}

export interface AssetView {
  assets: Asset[];
  depots: { depot_id: string; name: string; lat: number; lon: number }[];
  counts: Record<string, number>;
}

export interface Roads {
  open: [number, number][][];
  flooded: [number, number][][];
  disabled: [number, number][][];
  river: [number, number][];
  bridges: { lat: number; lon: number; standing: boolean }[];
  counts: { open: number; flooded: number; disabled: number };
}

export interface Zone {
  h3: string;
  boundary: [number, number][];
  people: number;
  served: number;
  coverage: number;
}

export interface Metrics {
  clock_minutes: number;
  messages_ingested: number;
  messages_total: number;
  demand_records: number;
  collapse_ratio: number;
  duplicates_collapsed: number;
  people_outstanding: number;
  people_served: number;
  resolved: number;
  in_flight: number;
  verification_dispatched: number;
  mean_confidence: number;
  mean_trust: number;
  solve_ms_last: number;
  solve_ms_mean: number;
  audit_entries: number;
  confidence_histogram: { bin: string; lower: number; count: number }[];
  trust_histogram: { bin: string; lower: number; count: number }[];
  resolution_mix: Record<string, number>;
  reserve: { assets_held: number; total_assets: number } | null;
}

export interface AuditEntry {
  id: number;
  at: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  evidence: Record<string, unknown>;
}

// --------------------------------------------------------------------------

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

async function post<T>(path: string): Promise<T> {
  const r = await fetch(path, { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export const api = {
  status: () => get<Status>("/api/status"),
  scenario: () => get<Scenario>("/api/scenario"),
  demands: (q: string) => get<DemandPage>(`/api/demands?${q}`),
  demand: (id: string) => get<DemandDetail>(`/api/demands/${id}`),
  plan: () => get<Plan>("/api/plan"),
  assets: () => get<AssetView>("/api/assets"),
  roads: () => get<Roads>("/api/roads"),
  zones: () => get<{ zones: Zone[]; count: number }>("/api/zones"),
  metrics: () => get<Metrics>("/api/metrics"),
  audit: () => get<AuditEntry[]>("/api/audit?limit=60"),
  events: () => get<{ at_min: number; kind: string; message: string }[]>("/api/events"),

  tick: () => post<Status>("/api/control/tick"),
  replan: () => post<Plan>("/api/control/replan"),
  setEquity: (w: number) => post<Plan>(`/api/control/equity?weight=${w}`),
  breakBridge: () => post<{ broken: unknown; remaining: number }>("/api/control/break-bridge"),
  redteam: (attack: string) => post<Record<string, unknown>>(`/api/control/redteam?attack=${attack}`),
  confidence: (cap: number | null) =>
    post<Status>(`/api/control/confidence${cap === null ? "" : `?cap=${cap}`}`),
  reset: () => post<Status>("/api/control/reset"),
};

// --------------------------------------------------------------------------
// display helpers

export const URGENCY_COLOR: Record<string, string> = {
  critical: "#ff5a5f",
  moderate: "#ff9f43",
  mild: "#ffd166",
  none: "#4dd4ac",
};

export const NEED_LABEL: Record<string, string> = {
  evacuation: "Evacuation",
  medical: "Medical",
  water: "Water",
  food: "Food",
  shelter: "Shelter",
  sanitation: "Sanitation",
  missing_person: "Missing",
  infrastructure: "Infrastructure",
};

/** What each resolution level entitles the map to draw. */
export const RESOLUTION_NOTE: Record<string, string> = {
  point: "GPS-accurate — drawn as a pin",
  building: "Building-accurate — drawn as a pin",
  street: "Street-level — drawn as a circle, not a pin",
  ward: "Ward-level only — drawn as a hex",
  unknown: "Not located — listed, never mapped",
};

export function clock(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `T+${h}:${String(m).padStart(2, "0")}`;
}
