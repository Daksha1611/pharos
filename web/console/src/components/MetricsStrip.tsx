/**
 * Live numbers along the bottom.
 *
 * The two that carry the pitch sit first: how many raw messages have arrived,
 * and how many distinct demands they collapsed into. That gap is the Kerala
 * number, computed live rather than quoted from a slide.
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
  const physical = assets?.assets.filter((a) => !a.is_verifier) ?? [];
  const committed = physical.filter((a) => a.state !== "idle").length;
  const latest = events && events.length ? events[events.length - 1] : null;

  return (
    <footer className="flex items-stretch gap-3 overflow-x-auto border-t border-gray-200 bg-white px-4 py-2">
      <Stat
        label="Messages ingested"
        value={m ? m.messages_ingested.toLocaleString() : "—"}
        sub={m ? `of ${m.messages_total.toLocaleString()} in scenario` : ""}
      />
      <Divider />
      <Stat
        label="Demand records"
        value={m ? m.demand_records.toLocaleString() : "—"}
        sub={m ? `${m.collapse_ratio.toFixed(2)}× collapse` : ""}
        accent="text-blue-700"
      />
      <Stat
        label="Duplicates removed"
        value={m ? m.duplicates_collapsed.toLocaleString() : "—"}
        sub="each would have pulled an asset"
        accent="text-indigo-700"
      />
      <Divider />
      <Stat
        label="People outstanding"
        value={m ? m.people_outstanding.toLocaleString() : "—"}
        sub={m ? `${m.people_served.toLocaleString()} reached` : ""}
      />
      <Stat
        label="Assets committed"
        value={physical.length ? `${committed}/${physical.length}` : "—"}
        sub={
          m?.reserve && m.reserve.assets_held > 0
            ? `${m.reserve.assets_held} held in reserve`
            : "fleet fully available"
        }
      />
      <Stat
        label="Verification tasks"
        value={plan ? String(plan.counts.verification) : "—"}
        sub="uncertainty → callback"
        accent="text-slate-700"
      />
      <Divider />
      <Stat
        label="Mean confidence"
        value={m ? m.mean_confidence.toFixed(2) : "—"}
        sub={m ? `mean trust ${m.mean_trust.toFixed(2)}` : ""}
      />
      <Stat
        label="Replan time"
        value={m ? `${Math.round(m.solve_ms_last)} ms` : "—"}
        sub={m ? `${Math.round(m.solve_ms_mean)} ms average` : ""}
      />
      <Stat
        label="Audit entries"
        value={m ? m.audit_entries.toLocaleString() : "—"}
        sub="immutable decision log"
      />

      <div className="ml-auto flex min-w-[220px] flex-col justify-center border-l border-gray-200 pl-3">
        <span className="text-[9px] font-medium uppercase tracking-wide text-slate-500">
          Latest event
        </span>
        {latest ? (
          <span className="truncate text-[11px] text-slate-700">
            <span className="font-mono text-slate-400">
              T+{Math.floor(latest.at_min / 60)}:
              {String(Math.round(latest.at_min % 60)).padStart(2, "0")}
            </span>{" "}
            {latest.message}
          </span>
        ) : (
          <span className="text-[11px] text-slate-400">Nothing yet</span>
        )}
      </div>
    </footer>
  );
}

function Stat({
  label,
  value,
  sub,
  accent = "text-slate-900",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="min-w-[118px] shrink-0">
      <div className="text-[9px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`font-mono text-base font-semibold leading-tight tabular-nums ${accent}`}>
        {value}
      </div>
      {sub && <div className="truncate text-[9px] leading-tight text-slate-500">{sub}</div>}
    </div>
  );
}

function Divider() {
  return <div className="w-px shrink-0 bg-gray-200" />;
}
