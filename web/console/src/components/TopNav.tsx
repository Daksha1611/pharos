/**
 * Top navigation: identity, clock, operator controls, and the mode switch.
 *
 * The equity control is the only genuinely operator-facing dial. The four
 * buttons beside it are the scripted demo beats, and each one runs the real
 * code path rather than an animation.
 */

import { useEffect, useState } from "react";

import type { Plan, Status } from "../api";
import type { Mode } from "../client";
import { clock } from "../theme";

interface Props {
  status: Status | undefined;
  plan: Plan | undefined;
  mode: Mode;
  onMode: (m: Mode) => void;
  busy: string | null;
  playing: boolean;
  showZones: boolean;
  onToggleZones: () => void;
  onTick: () => void;
  onPlay: () => void;
  onEquity: (w: number) => void;
  onBridge: () => void;
  onRedteam: (attack: string) => void;
  onConfidence: (cap: number | null) => void;
  onReset: () => void;
}

export function TopNav(p: Props) {
  const [equity, setEquity] = useState(p.status?.equity_weight ?? 0.5);
  useEffect(() => {
    if (p.status?.equity_weight !== undefined) setEquity(p.status.equity_weight);
  }, [p.status?.equity_weight]);

  const t = p.status?.clock_minutes ?? 0;
  const horizon = p.status?.horizon_minutes ?? 360;
  const degraded = p.plan?.mode === "decision_support";

  return (
    <header className="z-20 border-b border-gray-200 bg-white shadow-sm">
      <div className="flex items-center gap-5 px-5 py-2.5">
        {/* --- identity ------------------------------------------------- */}
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-800 text-sm font-bold text-white">
            P
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight text-slate-900">PHAROS</div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">
              District Operations
            </div>
          </div>
        </div>

        <div className="h-8 w-px bg-gray-200" />

        {/* --- clock ---------------------------------------------------- */}
        <div className="flex items-center gap-2.5">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Scenario clock</div>
            <div className="font-mono text-sm font-semibold tabular-nums text-slate-900">
              {clock(t)}
            </div>
          </div>
          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full rounded-full bg-slate-700 transition-all duration-500"
              style={{ width: `${(t / horizon) * 100}%` }}
            />
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <Btn onClick={p.onTick} busy={p.busy === "tick"} disabled={!!p.busy}>
            Step +{p.status?.tick_minutes ?? 15}m
          </Btn>
          <Btn onClick={p.onPlay} tone={p.playing ? "primary" : "default"}>
            {p.playing ? "Pause" : "Play"}
          </Btn>
        </div>

        <div className="h-8 w-px bg-gray-200" />

        {/* --- the operator's trade-off --------------------------------- */}
        <div className="flex items-center gap-2.5">
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
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
            disabled={!!p.busy}
            className="h-1.5 w-28 cursor-pointer appearance-none rounded-full bg-gray-200 accent-slate-700"
            title="Trade total throughput against coverage of the worst-served zones. Releasing re-solves."
          />
          <label className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
            Equity
          </label>
          <span className="w-8 font-mono text-xs font-semibold tabular-nums text-slate-700">
            {equity.toFixed(2)}
          </span>
        </div>

        {/* --- demo beats ------------------------------------------------ */}
        <div className="ml-auto flex items-center gap-1.5">
          <Btn onClick={p.onToggleZones} tone={p.showZones ? "primary" : "default"}>
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

          <div className="mx-1 h-8 w-px bg-gray-200" />
          <ModeSwitch mode={p.mode} onMode={p.onMode} />
        </div>
      </div>

      {/* --- degradation banner: unmissable by design -------------------- */}
      {p.plan?.banner && (
        <div className="flex items-center gap-3 border-t border-red-200 bg-red-50 px-5 py-2.5">
          <span className="rounded bg-red-700 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
            Decision support only
          </span>
          <span className="text-sm font-medium text-red-900">{p.plan.banner}</span>
          <span className="ml-auto text-xs text-red-700">
            No asset will be auto-assigned. Ranking and evidence stay live; dispatch is yours.
          </span>
        </div>
      )}
    </header>
  );
}

// --------------------------------------------------------------------------

function ModeSwitch({ mode, onMode }: { mode: Mode; onMode: (m: Mode) => void }) {
  const live = mode === "live";
  return (
    <button
      onClick={() => onMode(live ? "demo" : "live")}
      title={
        live
          ? "Reading the live API. Click to fall back to the captured snapshot."
          : "Reading a captured snapshot. Click to reconnect to the live API."
      }
      className={`flex items-center gap-2 rounded-full border px-1 py-1 pr-3 transition-colors
        ${live
          ? "border-emerald-300 bg-emerald-50 hover:bg-emerald-100"
          : "border-amber-300 bg-amber-50 hover:bg-amber-100"}`}
    >
      <span
        className={`flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold text-white
          ${live ? "bg-emerald-600" : "bg-amber-600"}`}
      >
        {live ? "●" : "▮"}
      </span>
      <span
        className={`text-[10px] font-bold uppercase tracking-wide ${
          live ? "text-emerald-800" : "text-amber-800"
        }`}
      >
        {live ? "Live API" : "Demo mode"}
      </span>
    </button>
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
  tone?: "default" | "primary" | "danger";
}) {
  const tones = {
    default:
      "border-gray-300 bg-white text-slate-700 hover:bg-gray-50 hover:border-gray-400",
    primary: "border-slate-700 bg-slate-700 text-white hover:bg-slate-800",
    danger: "border-red-300 bg-red-50 text-red-700 hover:bg-red-100",
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md border px-2.5 py-1.5 text-xs font-medium shadow-sm transition-colors
                  disabled:cursor-not-allowed disabled:opacity-50 ${tones[tone]}`}
    >
      {busy ? "…" : children}
    </button>
  );
}
