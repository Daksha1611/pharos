/**
 * Clock, operator controls, and the demo beats.
 *
 * The equity control is the only genuinely operator-facing dial here: moving it
 * re-solves and the plan visibly changes. The three buttons on the right are
 * the scripted demo moments - break a bridge, inject a hoax, drop confidence -
 * and each one exercises a real code path rather than a canned animation.
 */

import { useState } from "react";

import type { Plan, Status } from "../api";
import { clock } from "../api";

interface Props {
  status: Status | undefined;
  plan: Plan | undefined;
  busy: string | null;
  playing: boolean;
  onTick: () => void;
  onPlay: () => void;
  onEquity: (w: number) => void;
  onBridge: () => void;
  onRedteam: (attack: string) => void;
  onConfidence: (cap: number | null) => void;
  onReset: () => void;
  showZones: boolean;
  onToggleZones: () => void;
}

export function ControlBar(p: Props) {
  const [equity, setEquity] = useState(p.status?.equity_weight ?? 0.5);
  const t = p.status?.clock_minutes ?? 0;
  const horizon = p.status?.horizon_minutes ?? 360;
  const degraded = p.plan?.mode === "decision_support";

  return (
    <header className="border-b border-ink-700 bg-ink-900">
      <div className="flex items-center gap-4 px-4 py-2">
        {/* --- identity --------------------------------------------------- */}
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold tracking-tight text-slate-100">PHAROS</span>
          <span className="hidden text-[10px] uppercase tracking-wider text-slate-600 lg:inline">
            District operations
          </span>
        </div>

        {/* --- clock ------------------------------------------------------ */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm tabular-nums text-slate-200">{clock(t)}</span>
          <div className="h-1 w-28 overflow-hidden rounded-full bg-ink-700">
            <div
              className="h-full rounded-full bg-signal-info transition-all"
              style={{ width: `${(t / horizon) * 100}%` }}
            />
          </div>
        </div>

        <Btn onClick={p.onTick} busy={p.busy === "tick"} disabled={!!p.busy}>
          Step +{p.status?.tick_minutes ?? 15}m
        </Btn>
        <Btn onClick={p.onPlay} tone={p.playing ? "active" : "default"} disabled={!!p.busy && !p.playing}>
          {p.playing ? "Pause" : "Play"}
        </Btn>

        {/* --- the equity control ---------------------------------------- */}
        <div className="ml-2 flex items-center gap-2">
          <label className="text-[10px] uppercase tracking-wider text-slate-500">
            Efficiency
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={equity}
            onChange={(e) => setEquity(Number(e.target.value))}
            onMouseUp={() => p.onEquity(equity)}
            onTouchEnd={() => p.onEquity(equity)}
            className="h-1 w-32 cursor-pointer appearance-none rounded-full bg-ink-600
                       accent-signal-info"
            title="Move to trade total throughput against coverage of the worst-served zones. Releasing re-solves."
          />
          <label className="text-[10px] uppercase tracking-wider text-slate-500">Equity</label>
          <span className="w-8 font-mono text-[11px] text-slate-400">{equity.toFixed(2)}</span>
        </div>

        {/* --- solver health --------------------------------------------- */}
        <div className="ml-auto flex items-center gap-3 font-mono text-[11px] text-slate-500">
          {p.plan?.reserve && p.plan.reserve.assets_held > 0 && (
            <span
              className="rounded border border-signal-verify/40 px-1.5 py-0.5 text-signal-verify"
              title={p.plan.reserve.rationale}
            >
              {p.plan.reserve.assets_held} held in reserve
            </span>
          )}
          <span title={`solver returned ${p.plan?.solver_status}`}>
            {p.plan?.solver_status ?? "—"} · {Math.round(p.plan?.solve_time_ms ?? 0)}ms
          </span>
        </div>

        {/* --- demo beats -------------------------------------------------- */}
        <div className="flex items-center gap-1">
          <Btn onClick={p.onToggleZones} tone={p.showZones ? "active" : "default"}>
            Equity view
          </Btn>
          <Btn onClick={p.onBridge} busy={p.busy === "bridge"} disabled={!!p.busy}>
            Break bridge
          </Btn>
          <Btn
            onClick={() => p.onRedteam("hoax_cluster")}
            busy={p.busy === "redteam"}
            disabled={!!p.busy}
          >
            Inject hoax
          </Btn>
          <Btn
            onClick={() => p.onConfidence(degraded ? null : 0.3)}
            tone={degraded ? "danger" : "default"}
            busy={p.busy === "confidence"}
            disabled={!!p.busy}
          >
            {degraded ? "Restore confidence" : "Drop confidence"}
          </Btn>
          <Btn onClick={p.onReset} busy={p.busy === "reset"} disabled={!!p.busy}>
            Reset
          </Btn>
        </div>
      </div>

      {/* --- the unmissable banner ---------------------------------------- */}
      {p.plan?.banner && (
        <div className="flex items-center gap-3 border-t border-signal-critical/40 bg-signal-critical/10 px-4 py-2">
          <span className="rounded bg-signal-critical px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-ink-900">
            Decision support only
          </span>
          <span className="text-xs text-slate-200">{p.plan.banner}</span>
          <span className="ml-auto text-[11px] text-slate-400">
            No asset will be auto-assigned. Ranking and evidence remain live; dispatch is yours.
          </span>
        </div>
      )}
    </header>
  );
}

function Btn({
  children,
  onClick,
  disabled,
  busy,
  tone = "default",
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  tone?: "default" | "active" | "danger";
}) {
  const tones = {
    default: "border-ink-600 text-slate-400 hover:border-ink-500 hover:text-slate-200",
    active: "border-signal-info bg-signal-info/15 text-signal-info",
    danger: "border-signal-critical bg-signal-critical/15 text-signal-critical",
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded border px-2 py-1 text-[11px] transition-colors disabled:opacity-40
                  ${tones[tone]}`}
    >
      {busy ? "…" : children}
    </button>
  );
}
