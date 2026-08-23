/**
 * The live SOS feed: one sorted list, white cards, no hunting across channels.
 *
 * Every card explains itself without being opened. Four things are always
 * visible and each one is a claim this project makes:
 *
 *   Urgency   a 1-10 score with its band spelled out in words, never colour
 *             alone.
 *   Headcount the interval the solver plans against, never a bare number.
 *   Trust     a slate shield badge, deliberately not on the urgency palette,
 *             because a report can be critical and unverified at once.
 *   Merged    "Merged · 3 reports" wherever deduplication collapsed a cluster,
 *             so the duplicate-filtering claim is visible on screen rather
 *             than only asserted in the pitch.
 */

import type { Demand, DemandPage } from "../api";
import { NEED_ICON, NEED_LABEL, RESOLUTION_SHORT, URGENCY, ago, trustStyle } from "../theme";

export interface Filters {
  status: string;
  need: string;
  band: string;
  search: string;
}

export const EMPTY_FILTERS: Filters = { status: "", need: "", band: "", search: "" };

interface Props {
  page: DemandPage | undefined;
  selected: string | null;
  onSelect: (id: string) => void;
  filters: Filters;
  setFilters: (f: Filters) => void;
}

export function SosFeed({ page, selected, onSelect, filters, setFilters }: Props) {
  const c = page?.counts;

  return (
    <section className="flex h-full flex-col border-r border-gray-200 bg-gray-50">
      <div className="border-b border-gray-200 bg-white px-4 py-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-slate-900">Live SOS feed</h2>
          <span className="font-mono text-xs text-slate-500">
            {page ? `${page.demands.length} of ${page.total}` : "—"}
          </span>
        </div>
        <p className="mt-0.5 text-[11px] text-slate-500">
          Sorted by need against currently available capacity
        </p>

        <input
          value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          placeholder="Search reports, IDs, resolution method…"
          className="mt-2.5 w-full rounded-md border border-gray-300 bg-white px-2.5 py-1.5 text-xs
                     text-slate-800 placeholder:text-slate-400 focus:border-slate-500
                     focus:outline-none focus:ring-1 focus:ring-slate-500"
        />

        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Chip label="All" active={!filters.status && !filters.band}
                onClick={() => setFilters({ ...filters, status: "", band: "" })} />
          <Chip label="Unassigned" n={c?.by_status.unassigned} active={filters.status === "unassigned"}
                onClick={() => setFilters({ ...filters, status: "unassigned", band: "" })} />
          <Chip label="Verifying" n={c?.by_status.verifying} active={filters.status === "verifying"}
                onClick={() => setFilters({ ...filters, status: "verifying", band: "" })} />
          <Chip label="Unverified" n={c?.low_trust} active={filters.band === "lowtrust"}
                onClick={() => setFilters({ ...filters, band: "lowtrust", status: "" })} />
          <Chip label="Not located" n={c?.unlocatable} active={filters.band === "unlocated"}
                onClick={() => setFilters({ ...filters, band: "unlocated", status: "" })} />
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {!page && <p className="px-1 text-xs text-slate-500">Loading reports…</p>}
        {page?.demands.length === 0 && (
          <p className="px-1 text-xs text-slate-500">No reports match this filter.</p>
        )}
        {page?.demands.map((d) => (
          <Card key={d.demand_id} d={d} selected={d.demand_id === selected} onSelect={onSelect} />
        ))}
      </div>
    </section>
  );
}

// --------------------------------------------------------------------------

function Card({
  d,
  selected,
  onSelect,
}: {
  d: Demand;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const u = URGENCY[d.urgency_band];
  const t = trustStyle(d.trust_score);
  const stale = d.staleness_minutes > 120 && d.status === "unassigned";

  return (
    <button
      onClick={() => onSelect(d.demand_id)}
      className={`w-full rounded-lg border bg-white p-3 text-left shadow-sm transition-all
        hover:shadow-md ${selected ? "border-slate-700 ring-1 ring-slate-700" : "border-gray-200"}`}
    >
      {/* --- urgency: colour AND label, never colour alone -------------- */}
      <div className="flex items-start gap-2">
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded border px-1.5 py-0.5
                      text-[10px] font-semibold ${u.bg} ${u.text} ${u.border}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${u.dot}`} />
          {u.label}
          <span className="font-mono opacity-70">{d.urgency_score.toFixed(1)}</span>
        </span>

        <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-900">
          <span aria-hidden className="text-slate-400">{NEED_ICON[d.need] ?? "•"}</span>
          {NEED_LABEL[d.need] ?? d.need}
        </span>

        <span className="ml-auto shrink-0 font-mono text-[10px] text-slate-400">
          {ago(d.staleness_minutes)}
        </span>
      </div>

      {/* --- the interval, never a bare number --------------------------- */}
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-lg font-semibold leading-none tabular-nums text-slate-900">
          {d.people_lower === d.people_upper
            ? d.people
            : `${d.people_lower}–${d.people_upper}`}
        </span>
        <span className="text-xs text-slate-600">people</span>
        <span className="text-[10px] text-slate-400">
          {Math.round(d.quantity_confidence * 100)}% confidence
        </span>
      </div>

      <p className="mt-1.5 line-clamp-2 text-xs leading-snug text-slate-600">{d.preview}</p>

      {/* --- badges ------------------------------------------------------ */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {/* Trust: slate shield, deliberately off the urgency scale. */}
        <span
          className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]
                      font-medium ${t.bg} ${t.text} ${t.border}`}
          title={`Trust ${t.percent} — corroboration, source diversity, freshness`}
        >
          <Shield />
          {t.label}
          <span className="font-mono opacity-80">{t.percent}</span>
        </span>

        {/* Deduplication, made visible. */}
        {d.duplicate_collapse_count > 1 && (
          <span
            className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50
                       px-1.5 py-0.5 text-[10px] font-medium text-indigo-700"
            title="Deduplication collapsed these reports into one demand. Without it each would have pulled its own asset."
          >
            <Merge />
            Merged · {d.duplicate_collapse_count} reports
          </span>
        )}

        <span
          className="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500"
          title={d.location.method}
        >
          {RESOLUTION_SHORT[d.location.resolution]}
        </span>

        {d.vulnerability.length > 0 && (
          <span className="rounded border border-purple-200 bg-purple-50 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
            {d.vulnerability.join(", ")}
          </span>
        )}

        {stale && (
          <span
            className="rounded border border-orange-200 bg-orange-50 px-1.5 py-0.5 text-[10px] font-medium text-orange-700"
            title="Nobody has re-confirmed this in over two hours; its trust is decaying"
          >
            Unconfirmed 2h+
          </span>
        )}

        {d.assigned_asset && (
          <span
            className={`ml-auto rounded px-1.5 py-0.5 font-mono text-[10px] font-medium ${
              d.assignment_kind === "verification"
                ? "bg-slate-100 text-slate-600"
                : "bg-emerald-50 text-emerald-700"
            }`}
          >
            {d.assignment_kind === "verification" ? "verifying" : d.assigned_asset}
          </span>
        )}
      </div>
    </button>
  );
}

// --------------------------------------------------------------------------

function Chip({
  label,
  n,
  active,
  onClick,
}: {
  label: string;
  n?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md border px-2 py-0.5 text-[11px] font-medium transition-colors
        ${active
          ? "border-slate-700 bg-slate-700 text-white"
          : "border-gray-300 bg-white text-slate-600 hover:border-gray-400 hover:bg-gray-50"}`}
    >
      {label}
      {n !== undefined && (
        <span className={`ml-1 font-mono ${active ? "text-white/70" : "text-slate-400"}`}>{n}</span>
      )}
    </button>
  );
}

function Shield() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor" aria-hidden>
      <path d="M8 1l5 2v4.5c0 3.2-2.1 6.1-5 7-2.9-.9-5-3.8-5-7V3l5-2z" opacity="0.25" />
      <path d="M8 1l5 2v4.5c0 3.2-2.1 6.1-5 7-2.9-.9-5-3.8-5-7V3l5-2zm0 1.6L4.5 4v3.5c0 2.5 1.5 4.7 3.5 5.5 2-.8 3.5-3 3.5-5.5V4L8 2.6z" />
    </svg>
  );
}

function Merge() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M4 2v4c0 2 1.5 3 3 3h5" strokeLinecap="round" />
      <path d="M12 2v4c0 2-1.5 3-3 3H7" strokeLinecap="round" opacity="0.5" />
      <path d="M10 7l2 2-2 2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
