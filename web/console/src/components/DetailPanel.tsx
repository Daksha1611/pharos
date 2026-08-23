/**
 * The full demand record: the seam object, its provenance, and the reasoning.
 *
 * Three things belong here and nowhere else.
 *
 * Provenance. Every source message, as the citizen actually wrote it, beside
 * what the extractor read out of it. An operator who cannot see the original
 * text cannot audit the machine, and a machine that cannot be audited will not
 * be trusted at 3 AM.
 *
 * The interval and its confidence, together, always. The panel states what was
 * committed and what was credited, because that asymmetry is the decision.
 *
 * The justification trace, including what was rejected. "truck-38 was closer
 * and was out of capacity" is the line that turns an assignment from an
 * instruction into an argument.
 */

import type { DemandDetail } from "../api";
import { NEED_LABEL, RESOLUTION_NOTE, URGENCY, ago, hhmm, trustStyle } from "../theme";

interface Props {
  detail: DemandDetail | undefined;
  loading: boolean;
  onClose: () => void;
}

export function DetailPanel({ detail, loading, onClose }: Props) {
  if (loading && !detail) return <Shell onClose={onClose}><Muted>Loading record…</Muted></Shell>;

  if (!detail) {
    return (
      <Shell onClose={onClose}>
        <Muted>
          Select a report from the feed or a marker on the map to see its full record — every
          message it was built from, what the extractor read, and why it was assigned as it was.
        </Muted>
      </Shell>
    );
  }

  const d = detail;
  const u = URGENCY[d.urgency_band];
  const t = trustStyle(d.trust_score);

  return (
    <Shell onClose={onClose}>
      {/* --- header ----------------------------------------------------- */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-[10px]
                        font-semibold ${u.bg} ${u.text} ${u.border}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${u.dot}`} />
            {u.label}
            <span className="font-mono opacity-70">{d.urgency_score.toFixed(1)}</span>
          </span>
          <h3 className="text-base font-semibold text-slate-900">
            {NEED_LABEL[d.need] ?? d.need}
          </h3>
        </div>
        <p className="mt-1 font-mono text-[10px] text-slate-400">{d.demand_id}</p>
      </div>

      {/* --- the interval, never a bare number --------------------------- */}
      <Card title="How many people">
        <div className="flex items-end gap-3">
          <div>
            <div className="font-mono text-3xl font-semibold leading-none tabular-nums text-slate-900">
              {d.people_lower}–{d.people_upper}
            </div>
            <div className="mt-1 text-[10px] text-slate-500">point estimate {d.people}</div>
          </div>
          <p className="flex-1 text-[11px] leading-relaxed text-slate-600">
            The solver commits <b className="text-slate-900">{d.people_upper} seats</b> and credits
            itself <b className="text-slate-900">{d.people_lower}</b>. Plan capacity for the worst
            case, count value for the best-confirmed case.
          </p>
        </div>
        <Bars
          rows={[
            ["Headcount confidence", d.quantity_confidence, "bg-blue-500"],
            ["Need type confidence", d.field_confidence.need_type, "bg-blue-400"],
            ["Location confidence", d.location.geo_confidence, "bg-slate-400"],
          ]}
        />
      </Card>

      {/* --- trust, on its own track ------------------------------------ */}
      <Card title="Trust">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-medium
                        ${t.bg} ${t.text} ${t.border}`}
          >
            <Shield />
            {t.label}
            <span className="font-mono">{t.percent}</span>
          </span>
          <p className="text-[11px] leading-snug text-slate-600">
            From {d.duplicate_collapse_count} report
            {d.duplicate_collapse_count === 1 ? "" : "s"} across{" "}
            {d.channels.length || 1} channel{d.channels.length === 1 ? "" : "s"}.
          </p>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
          Trust is a separate signal from urgency: corroboration, how independent the sources are,
          and how recently anyone confirmed it. It suppresses a report's claim on assets rather
          than removing it from the queue.
        </p>
        <KV k="Last confirmed" v={`${hhmm(d.last_corroborated_at)} · ${ago(d.staleness_minutes)}`} mono />
        {d.staleness_minutes > 120 && (
          <Note tone="warn">
            Nobody has re-confirmed this in over two hours. Trust decays with a 90-minute
            half-life, so it is quietly losing its claim on assets instead of generating calls
            forever — the 2021 stale-lead failure, handled.
          </Note>
        )}
      </Card>

      {/* --- location honesty -------------------------------------------- */}
      <Card title="Where">
        <p className="text-xs font-medium text-slate-800">
          {RESOLUTION_NOTE[d.location.resolution]}
        </p>
        <KV k="Resolved by" v={d.location.method} mono />
        {d.location.render_as !== "list_only" && (
          <KV
            k="Coordinates"
            v={`${d.location.lat.toFixed(5)}, ${d.location.lon.toFixed(5)}`}
            mono
          />
        )}
        {d.cluster_spread_m > 0 && (
          <KV k="Reports spread" v={`${Math.round(d.cluster_spread_m)} m apart`} mono />
        )}
        {d.needs_disambiguation && (
          <Note tone="warn">
            No usable location. This report is real and stays in the queue, but it is never drawn on
            the map as though we knew where it was. It is queued for a human to disambiguate.
          </Note>
        )}
      </Card>

      {/* --- the decision ------------------------------------------------ */}
      {d.assignment && (
        <Card
          title={d.assignment.kind === "verification" ? "Dispatched to verify" : "Assignment"}
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-sm font-semibold text-slate-900">
              {d.assignment.asset_id}
            </span>
            <span className="font-mono text-xs text-slate-500">
              {d.assignment.travel_minutes} min
            </span>
          </div>
          <ul className="mt-2 space-y-1.5 border-t border-gray-100 pt-2">
            {d.assignment.reasons.map((r, i) => (
              <li key={i} className="text-[11px] leading-snug">
                <span className="font-mono text-[10px] uppercase tracking-wide text-slate-400">
                  {r.factor.replace(/_/g, " ")}
                </span>
                <br />
                <span className="text-slate-700">{r.value}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!d.assignment && d.unserved_reason && (
        <Card title="Why nothing is coming yet">
          <p className="text-[11px] leading-relaxed text-slate-700">{d.unserved_reason}</p>
        </Card>
      )}

      {/* --- provenance --------------------------------------------------- */}
      <Card title={`Source messages (${d.sources.length})`}>
        {d.sources.length === 0 && (
          <Muted>Source text is not included in the captured snapshot. Switch to Live API.</Muted>
        )}
        <div className="space-y-2">
          {d.sources.slice(0, 8).map((s) => (
            <div key={s.message_id} className="rounded-md border border-gray-200 bg-gray-50 p-2">
              <div className="flex flex-wrap items-center gap-1.5 text-[9px] text-slate-500">
                <span className="rounded bg-white px-1 py-px font-mono uppercase tracking-wide text-slate-600 ring-1 ring-gray-200">
                  {s.channel}
                </span>
                <span className="font-mono uppercase">{s.language}</span>
                <span className="font-mono">{hhmm(s.received_at)}</span>
                <span className="ml-auto font-mono">{s.sender}</span>
              </div>
              {/* What the citizen actually wrote. */}
              <p className="mt-1.5 text-[11px] leading-snug text-slate-800">“{s.raw_text}”</p>
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-500">
                <span>
                  read as <b className="font-medium text-slate-700">{s.extracted.need}</b>
                </span>
                <span>
                  {s.extracted.people} people
                  <span className="text-slate-400"> via {s.extracted.people_method}</span>
                </span>
                <span>
                  located by <b className="font-medium text-slate-700">{s.resolved_by}</b> →{" "}
                  {s.resolution}
                </span>
              </div>
            </div>
          ))}
          {d.sources.length > 8 && (
            <p className="text-[10px] text-slate-400">
              …and {d.sources.length - 8} more reports in this cluster
            </p>
          )}
        </div>
      </Card>
    </Shell>
  );
}

// --------------------------------------------------------------------------

function Shell({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <aside className="flex h-full flex-col border-l border-gray-200 bg-gray-50">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">Demand record</h2>
        <button
          onClick={onClose}
          className="rounded p-1 text-slate-400 transition-colors hover:bg-gray-100 hover:text-slate-700"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">{children}</div>
    </aside>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm">
      <h4 className="mb-2 text-[10px] font-bold uppercase tracking-wide text-slate-500">{title}</h4>
      {children}
    </section>
  );
}

function KV({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="mt-1 flex justify-between gap-3 text-[11px]">
      <span className="shrink-0 text-slate-500">{k}</span>
      <span className={`text-right text-slate-800 ${mono ? "font-mono" : ""}`}>{v}</span>
    </div>
  );
}

function Bars({ rows }: { rows: [string, number, string][] }) {
  return (
    <div className="mt-3 space-y-1.5 border-t border-gray-100 pt-2.5">
      {rows.map(([label, value, colour]) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-36 shrink-0 text-[10px] text-slate-500">{label}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200">
            <span
              className={`block h-full rounded-full transition-all ${colour}`}
              style={{ width: `${Math.max(2, value * 100)}%` }}
            />
          </span>
          <span className="w-8 shrink-0 text-right font-mono text-[10px] tabular-nums text-slate-600">
            {value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function Note({ tone, children }: { tone: "warn" | "info"; children: React.ReactNode }) {
  const c =
    tone === "warn"
      ? "border-orange-200 bg-orange-50 text-orange-900"
      : "border-blue-200 bg-blue-50 text-blue-900";
  return (
    <p className={`mt-2 rounded-md border px-2 py-1.5 text-[11px] leading-snug ${c}`}>{children}</p>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="px-1 text-xs leading-relaxed text-slate-500">{children}</p>;
}

function Shield() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
      <path d="M8 1l5 2v4.5c0 3.2-2.1 6.1-5 7-2.9-.9-5-3.8-5-7V3l5-2zm0 1.6L4.5 4v3.5c0 2.5 1.5 4.7 3.5 5.5 2-.8 3.5-3 3.5-5.5V4L8 2.6z" />
    </svg>
  );
}
