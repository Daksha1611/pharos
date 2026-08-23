/**
 * The demand detail panel: the seam object, its provenance, and the reasoning.
 *
 * Three things belong here and nowhere else.
 *
 * Provenance. Every source message, as the citizen actually wrote it, next to
 * what the extractor read out of it. An operator who cannot see the original
 * text cannot audit the machine, and a system that cannot be audited will not
 * be trusted at 3 AM.
 *
 * The interval and its confidence, together, always. The panel says what was
 * committed and what was credited, because that asymmetry is the decision.
 *
 * The justification trace, including what was rejected. "boat-07 rejected: 63
 * min versus 41" is the line that turns an assignment from an instruction into
 * an argument.
 */

import type { DemandDetail } from "../api";
import { NEED_LABEL, RESOLUTION_NOTE, URGENCY_COLOR } from "../api";

interface Props {
  detail: DemandDetail | undefined;
  loading: boolean;
  onClose: () => void;
}

export function DetailPanel({ detail, loading, onClose }: Props) {
  if (loading && !detail) {
    return <Shell onClose={onClose}><p className="text-xs text-slate-500">Loading…</p></Shell>;
  }
  if (!detail) {
    return (
      <Shell onClose={onClose}>
        <p className="text-xs text-slate-500">
          Select a demand from the queue or the map to see its full record,
          every message it was built from, and why it was assigned as it was.
        </p>
      </Shell>
    );
  }

  const d = detail;
  return (
    <Shell onClose={onClose}>
      {/* --- header ------------------------------------------------------ */}
      <div className="flex items-start gap-2">
        <span
          className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
          style={{ background: URGENCY_COLOR[d.urgency] }}
        />
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-100">
            {NEED_LABEL[d.need] ?? d.need}
            <span className="ml-2 text-xs font-normal text-slate-400">{d.urgency} urgency</span>
          </h3>
          <p className="font-mono text-[10px] text-slate-600">{d.demand_id}</p>
        </div>
      </div>

      {/* --- the interval, never a bare number ---------------------------- */}
      <Section title="How many people">
        <div className="flex items-end gap-3">
          <div>
            <div className="font-mono text-2xl leading-none text-slate-100">
              {d.people_lower}–{d.people_upper}
            </div>
            <div className="mt-1 text-[10px] text-slate-500">
              point estimate {d.people}
            </div>
          </div>
          <div className="flex-1 text-[11px] leading-relaxed text-slate-400">
            The solver commits <b className="text-slate-200">{d.people_upper} seats</b> and credits
            itself <b className="text-slate-200">{d.people_lower}</b>. Plan for the worst case,
            count value for the best-confirmed case.
          </div>
        </div>
        <Bars
          rows={[
            ["headcount confidence", d.quantity_confidence, "#5aa9ff"],
            ["trust", d.trust_score, "#b388ff"],
            ["need type confidence", d.field_confidence.need_type, "#4dd4ac"],
            ["geo confidence", d.location.geo_confidence, "#ffd166"],
          ]}
        />
      </Section>

      {/* --- location honesty -------------------------------------------- */}
      <Section title="Where">
        <KV k="Resolution" v={d.location.resolution} mono />
        <p className="mt-1 text-[11px] text-slate-400">{RESOLUTION_NOTE[d.location.resolution]}</p>
        <KV k="Resolved by" v={d.location.method} mono />
        {d.location.render_as !== "list_only" && (
          <KV k="Coordinates" v={`${d.location.lat.toFixed(5)}, ${d.location.lon.toFixed(5)}`} mono />
        )}
        {d.needs_disambiguation && (
          <Callout tone="warn">
            No usable location. This demand is real and stays in the queue, but it is never drawn
            on the map as though we knew where it was. It is queued for a human to disambiguate.
          </Callout>
        )}
        {d.cluster_spread_m > 0 && (
          <KV k="Report spread" v={`${Math.round(d.cluster_spread_m)} m apart`} mono />
        )}
      </Section>

      {/* --- corroboration ------------------------------------------------ */}
      <Section title="Corroboration">
        <KV k="Reports collapsed" v={`${d.duplicate_collapse_count}`} mono />
        <KV k="Channels" v={d.channels.join(", ") || "—"} />
        <KV k="First reported" v={fmt(d.first_reported_at)} mono />
        <KV k="Last confirmed" v={`${fmt(d.last_corroborated_at)} (${Math.round(d.staleness_minutes)} min ago)`} mono />
        {d.staleness_minutes > 120 && (
          <Callout tone="warn">
            Nobody has re-confirmed this in over two hours. Trust decays with a 90-minute
            half-life, so it is quietly losing its claim on assets rather than generating calls
            forever.
          </Callout>
        )}
      </Section>

      {/* --- the decision ------------------------------------------------- */}
      {d.assignment && (
        <Section
          title={d.assignment.kind === "verification" ? "Dispatched to verify" : "Assignment"}
        >
          <div className="rounded border border-ink-600 bg-ink-900/60 p-2">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-slate-200">{d.assignment.asset_id}</span>
              <span className="font-mono text-[11px] text-slate-400">
                {d.assignment.travel_minutes} min
              </span>
            </div>
            <ul className="mt-2 space-y-1.5">
              {d.assignment.reasons.map((r, i) => (
                <li key={i} className="text-[11px] leading-snug">
                  <span className="font-mono text-slate-500">{r.factor}</span>
                  <span className="mx-1 text-slate-700">·</span>
                  <span className="text-slate-300">{r.value}</span>
                  {r.contribution !== null && (
                    <span className="ml-1 font-mono text-slate-600">
                      ({(r.contribution * 100).toFixed(0)}%)
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </Section>
      )}

      {!d.assignment && d.unserved_reason && (
        <Section title="Why nothing is coming yet">
          <Callout tone="info">{d.unserved_reason}</Callout>
        </Section>
      )}

      {/* --- provenance --------------------------------------------------- */}
      <Section title={`Source messages (${d.sources.length})`}>
        <div className="space-y-2">
          {d.sources.slice(0, 8).map((s) => (
            <div key={s.message_id} className="rounded border border-ink-700 bg-ink-900/50 p-2">
              <div className="flex items-center gap-2 text-[10px] text-slate-500">
                <span className="rounded bg-ink-700 px-1 font-mono">{s.channel}</span>
                <span className="font-mono">{s.language}</span>
                <span className="font-mono">{fmt(s.received_at)}</span>
                <span className="ml-auto font-mono">{s.sender}</span>
              </div>
              {/* What the citizen actually wrote. */}
              <p className="mt-1 text-[11px] leading-snug text-slate-300">“{s.raw_text}”</p>
              {s.normalized_text && s.normalized_text !== s.raw_text.toLowerCase() && (
                <p className="mt-1 text-[10px] leading-snug text-slate-600">
                  normalized: {s.normalized_text}
                </p>
              )}
              <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-slate-500">
                <span>read as <b className="text-slate-400">{s.extracted.need}</b></span>
                <span>
                  {s.extracted.people} people
                  <span className="text-slate-700"> via {s.extracted.people_method}</span>
                </span>
                <span>located by <b className="text-slate-400">{s.resolved_by}</b> → {s.resolution}</span>
              </div>
            </div>
          ))}
          {d.sources.length > 8 && (
            <p className="text-[10px] text-slate-600">
              …and {d.sources.length - 8} more reports in this cluster
            </p>
          )}
        </div>
      </Section>
    </Shell>
  );
}

// --------------------------------------------------------------------------

function Shell({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <aside className="flex h-full flex-col border-l border-ink-700 bg-ink-800">
      <div className="flex items-center justify-between border-b border-ink-700 px-3 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Demand record
        </h2>
        <button onClick={onClose} className="text-xs text-slate-600 hover:text-slate-300">
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-3">{children}</div>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
        {title}
      </h4>
      {children}
    </section>
  );
}

function KV({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3 py-px text-[11px]">
      <span className="shrink-0 text-slate-500">{k}</span>
      <span className={`text-right text-slate-300 ${mono ? "font-mono" : ""}`}>{v}</span>
    </div>
  );
}

function Bars({ rows }: { rows: [string, number, string][] }) {
  return (
    <div className="mt-3 space-y-1">
      {rows.map(([label, value, colour]) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-32 shrink-0 text-[10px] text-slate-500">{label}</span>
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-600">
            <span
              className="block h-full rounded-full transition-all"
              style={{ width: `${Math.max(2, value * 100)}%`, background: colour }}
            />
          </span>
          <span className="w-8 shrink-0 text-right font-mono text-[10px] text-slate-400">
            {value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function Callout({ tone, children }: { tone: "warn" | "info"; children: React.ReactNode }) {
  const c =
    tone === "warn"
      ? "border-signal-high/40 bg-signal-high/5 text-signal-high"
      : "border-signal-info/40 bg-signal-info/5 text-slate-300";
  return <p className={`mt-2 rounded border px-2 py-1.5 text-[11px] leading-snug ${c}`}>{children}</p>;
}

function fmt(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}
