/**
 * Live numbers, along the bottom of the map.
 *
 * The two that matter for the pitch sit first: how many raw messages have been
 * ingested, and how many distinct demands they collapsed into. That difference
 * is the Kerala number, computed live rather than quoted from a slide.
 */

import type { AssetView, Metrics, Plan } from "../api";

interface Props {
  metrics: Metrics | undefined;
  plan: Plan | undefined;
  assets: AssetView | undefined;
  events: { at_min: number; kind: string; message: string }[] | undefined;
}

export function MetricsStrip({ metrics, plan, assets, events }: Props) {
  const m = metrics;
  const collapsed = m ? m.duplicates_collapsed : 0;

  return (
    <div className="flex items-stretch gap-px overflow-x-auto border-t border-ink-700 bg-ink-900">
      <Stat
        label="messages in"
        value={m ? m.messages_ingested.toLocaleString() : "—"}
        sub={m ? `of ${m.messages_total.toLocaleString()}` : ""}
      />
      <Stat
        label="demand records"
        value={m ? m.demand_records.toLocaleString() : "—"}
        sub={m ? `${m.collapse_ratio.toFixed(2)}× collapse` : ""}
        tone="info"
      />
      <Stat
        label="duplicates removed"
        value={collapsed.toLocaleString()}
        sub="each one would have pulled an asset"
        tone="good"
      />
      <Stat
        label="people outstanding"
        value={m ? m.people_outstanding.toLocaleString() : "—"}
        sub={m ? `${m.people_served.toLocaleString()} served` : ""}
      />
      <Stat
        label="assets committed"
        value={
          assets
            ? `${assets.assets.filter((a) => !a.is_verifier && a.state !== "idle").length}`
            : "—"
        }
        sub={assets ? `of ${assets.assets.filter((a) => !a.is_verifier).length}` : ""}
      />
      <Stat
        label="verification tasks"
        value={plan ? String(plan.counts.verification) : "—"}
        sub="uncertainty → callback"
        tone="verify"
      />
      <Stat
        label="mean confidence"
        value={m ? m.mean_confidence.toFixed(2) : "—"}
        sub={m ? `trust ${m.mean_trust.toFixed(2)}` : ""}
      />
      <Stat
        label="replan"
        value={m ? `${Math.round(m.solve_ms_last)}ms` : "—"}
        sub={m ? `${Math.round(m.solve_ms_mean)}ms mean` : ""}
      />
      <Stat
        label="audit entries"
        value={m ? m.audit_entries.toLocaleString() : "—"}
        sub="every decision, immutable"
      />

      {/* --- most recent scenario event ---------------------------------- */}
      <div className="flex min-w-[240px] flex-1 flex-col justify-center px-3 py-1.5">
        <span className="text-[9px] uppercase tracking-wider text-slate-600">latest event</span>
        {events && events.length > 0 ? (
          <span className="truncate text-[11px] text-slate-300">
            <span className="font-mono text-slate-600">
              T+{Math.floor(events[events.length - 1].at_min / 60)}:
              {String(Math.round(events[events.length - 1].at_min % 60)).padStart(2, "0")}
            </span>{" "}
            {events[events.length - 1].message}
          </span>
        ) : (
          <span className="text-[11px] text-slate-600">nothing yet</span>
        )}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "info" | "good" | "verify";
}) {
  const colour = {
    default: "text-slate-200",
    info: "text-signal-info",
    good: "text-signal-low",
    verify: "text-signal-verify",
  }[tone];
  return (
    <div className="min-w-[112px] shrink-0 bg-ink-800 px-3 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-600">{label}</div>
      <div className={`font-mono text-sm tabular-nums ${colour}`}>{value}</div>
      {sub && <div className="truncate text-[9px] text-slate-600">{sub}</div>}
    </div>
  );
}
