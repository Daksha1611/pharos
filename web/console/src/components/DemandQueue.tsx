/**
 * The sorted demand queue.
 *
 * One list, not ten channels. Every row explains itself without being opened:
 * what is needed, for how many people, how sure we are of that number, how far
 * the report is trusted, and how long since anyone confirmed it.
 *
 * The headcount is never shown as a bare number. It is shown as the interval
 * the solver actually plans against, because "7" and "5 to 12" call for
 * different decisions and hiding the difference is how an operator gets
 * misled.
 */

import type { Demand, DemandPage } from "../api";
import { NEED_LABEL, URGENCY_COLOR } from "../api";

interface Props {
  page: DemandPage | undefined;
  selected: string | null;
  onSelect: (id: string) => void;
  filters: Filters;
  setFilters: (f: Filters) => void;
}

export interface Filters {
  status: string;
  need: string;
  band: string;
  search: string;
}

export const EMPTY_FILTERS: Filters = { status: "", need: "", band: "", search: "" };

export function DemandQueue({ page, selected, onSelect, filters, setFilters }: Props) {
  const counts = page?.counts;

  return (
    <div className="flex h-full flex-col border-r border-ink-700 bg-ink-800">
      <div className="border-b border-ink-700 px-3 py-2">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            Demand queue
          </h2>
          <span className="font-mono text-[11px] text-slate-500">
            {page ? `${page.demands.length} of ${page.total}` : "—"}
          </span>
        </div>

        <input
          value={filters.search}
          onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          placeholder="Search text, id, resolution method…"
          className="mt-2 w-full rounded border border-ink-600 bg-ink-900 px-2 py-1 text-xs
                     text-slate-200 placeholder:text-slate-600 focus:border-signal-info
                     focus:outline-none"
        />

        <div className="mt-2 flex flex-wrap gap-1">
          <Chip
            label="All"
            active={!filters.status && !filters.band}
            onClick={() => setFilters({ ...filters, status: "", band: "" })}
          />
          <Chip
            label="Unassigned"
            n={counts?.by_status.unassigned}
            active={filters.status === "unassigned"}
            onClick={() => setFilters({ ...filters, status: "unassigned", band: "" })}
          />
          <Chip
            label="Verifying"
            n={counts?.by_status.verifying}
            active={filters.status === "verifying"}
            onClick={() => setFilters({ ...filters, status: "verifying", band: "" })}
          />
          <Chip
            label="Low confidence"
            n={counts?.low_confidence}
            active={filters.band === "lowconf"}
            onClick={() => setFilters({ ...filters, band: "lowconf", status: "" })}
          />
          <Chip
            label="Low trust"
            n={counts?.low_trust}
            active={filters.band === "lowtrust"}
            onClick={() => setFilters({ ...filters, band: "lowtrust", status: "" })}
          />
          <Chip
            label="Not located"
            n={counts?.unlocatable}
            active={filters.band === "unlocated"}
            onClick={() => setFilters({ ...filters, band: "unlocated", status: "" })}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!page && <div className="p-4 text-xs text-slate-500">Loading…</div>}
        {page?.demands.length === 0 && (
          <div className="p-4 text-xs text-slate-500">Nothing matches this filter.</div>
        )}
        {page?.demands.map((d) => (
          <Row key={d.demand_id} d={d} selected={d.demand_id === selected} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------

function Row({
  d,
  selected,
  onSelect,
}: {
  d: Demand;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  const stale = d.staleness_minutes > 120 && d.status === "unassigned";
  return (
    <button
      onClick={() => onSelect(d.demand_id)}
      className={`w-full border-b border-ink-700/60 px-3 py-2 text-left transition-colors
        ${selected ? "bg-ink-600" : "hover:bg-ink-700/60"}`}
    >
      <div className="flex items-center gap-2">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: URGENCY_COLOR[d.urgency] }}
          title={`${d.urgency} urgency`}
        />
        <span className="text-xs font-medium text-slate-200">
          {NEED_LABEL[d.need] ?? d.need}
        </span>

        {/* The interval, not a bare number. */}
        <span className="font-mono text-[11px] text-slate-400">
          {d.people_lower === d.people_upper
            ? `${d.people} people`
            : `${d.people_lower}–${d.people_upper} people`}
        </span>

        <span className="ml-auto flex items-center gap-1">
          {d.duplicate_collapse_count > 1 && (
            <Tag title={`${d.duplicate_collapse_count} reports collapsed into this demand`}>
              ×{d.duplicate_collapse_count}
            </Tag>
          )}
          {d.assignment_kind === "verification" && (
            <Tag className="border-signal-verify/40 text-signal-verify">verifying</Tag>
          )}
          {d.assigned_asset && d.assignment_kind === "rescue" && (
            <Tag className="border-signal-info/40 text-signal-info">{d.assigned_asset}</Tag>
          )}
          {stale && (
            <Tag className="border-signal-high/40 text-signal-high" title="Nobody has re-confirmed this in over two hours">
              stale
            </Tag>
          )}
        </span>
      </div>

      <div className="mt-1 truncate text-[11px] text-slate-500">{d.preview}</div>

      <div className="mt-1.5 flex items-center gap-3">
        <Meter label="conf" value={d.quantity_confidence} colour="#5aa9ff" />
        <Meter label="trust" value={d.trust_score} colour="#b388ff" />
        <span
          className="font-mono text-[10px] text-slate-600"
          title={d.location.method}
        >
          {d.location.resolution}
        </span>
        {d.vulnerability.length > 0 && (
          <span className="text-[10px] text-signal-medium">{d.vulnerability.join(", ")}</span>
        )}
      </div>
    </button>
  );
}

function Meter({ label, value, colour }: { label: string; value: number; colour: string }) {
  return (
    <span className="flex items-center gap-1" title={`${label} ${value.toFixed(2)}`}>
      <span className="font-mono text-[10px] text-slate-600">{label}</span>
      <span className="h-1 w-9 overflow-hidden rounded-full bg-ink-600">
        <span
          className="block h-full rounded-full"
          style={{ width: `${Math.max(3, value * 100)}%`, background: colour }}
        />
      </span>
      <span className="font-mono text-[10px] text-slate-500">{value.toFixed(2)}</span>
    </span>
  );
}

function Tag({
  children,
  className = "",
  title,
}: {
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`rounded border border-ink-500 px-1 py-px font-mono text-[10px] text-slate-400 ${className}`}
    >
      {children}
    </span>
  );
}

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
      className={`rounded border px-1.5 py-0.5 text-[10px] transition-colors
        ${active
          ? "border-signal-info bg-signal-info/15 text-signal-info"
          : "border-ink-600 text-slate-500 hover:border-ink-500 hover:text-slate-300"}`}
    >
      {label}
      {n !== undefined && <span className="ml-1 font-mono opacity-70">{n}</span>}
    </button>
  );
}
