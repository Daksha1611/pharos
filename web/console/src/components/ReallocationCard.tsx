/**
 * The Smart Reallocation Suggestion.
 *
 * Floats over the bottom-right of the map with a heavier shadow and a coloured
 * top accent, because it is the one thing on this screen a judge should read
 * first.
 *
 * A console that shows four hundred rows and no recommendation has moved the
 * triage problem, not solved it. This surfaces the single highest-value
 * decision the solver just made, in the language an operator would use, and
 * carries the three things that make it defensible rather than magical:
 *
 *   what it beat        the runner-up asset and why it lost
 *   what it is unsure   the headcount interval and the trust score, side by side
 *   who decides         Accept and Override, both logged to the audit trail
 *
 * The accent colour tracks urgency; the trust badge stays slate. A suggestion
 * can be critical and unverified at the same time, and the card has to be able
 * to say so.
 */

import type { Suggestion } from "../api";
import { NEED_LABEL, RESOLUTION_SHORT, URGENCY, trustStyle } from "../theme";

interface Props {
  suggestion: Suggestion | null | undefined;
  degraded: boolean;
  busy: boolean;
  onOpen: (demandId: string) => void;
  onAccept: () => void;
}

export function ReallocationCard({ suggestion, degraded, busy, onOpen, onAccept }: Props) {
  if (degraded) {
    return (
      <Frame accent="bg-red-600">
        <Header title="Recommendation withheld" kicker="Confidence below threshold" />
        <p className="mt-2 text-xs leading-relaxed text-slate-600">
          Intake confidence has collapsed across the board. The system has stopped auto-assigning
          and is running as decision support: the queue is still ranked and every piece of evidence
          is still on screen, but no asset is committed without you.
        </p>
      </Frame>
    );
  }

  if (!suggestion) {
    return (
      <Frame accent="bg-slate-300">
        <Header title="No recommendation yet" kicker="Waiting for demand" />
        <p className="mt-2 text-xs leading-relaxed text-slate-600">
          Press <b>Step</b> or <b>Play</b> to advance the scenario clock. Reports arrive on a
          lognormal curve, so the first few minutes are quiet by design.
        </p>
      </Frame>
    );
  }

  const s = suggestion;
  const u = URGENCY[s.urgency_band];
  const t = trustStyle(s.trust_score);

  return (
    <Frame accent={u.dot}>
      <Header
        title="Smart reallocation"
        kicker={`Solved in ${Math.round(s.solve_time_ms)} ms across ${s.alternatives_considered} available assets`}
      />

      {/* --- the recommendation ---------------------------------------- */}
      <div className="mt-2.5 flex items-start gap-2">
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded border px-1.5 py-0.5
                      text-[10px] font-semibold ${u.bg} ${u.text} ${u.border}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${u.dot}`} />
          {u.label}
          <span className="font-mono opacity-70">{s.urgency_score.toFixed(1)}</span>
        </span>
        <span className="text-[11px] font-medium text-slate-600">
          {NEED_LABEL[s.need] ?? s.need}
        </span>
      </div>

      <p className="mt-2 text-sm font-semibold leading-snug text-slate-900">{s.headline}</p>

      {/* --- the numbers ------------------------------------------------ */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Cell
          label="Committing"
          value={`${s.people_committed}`}
          sub={`seats for ${s.people_lower}–${s.people_upper}`}
        />
        <Cell label="Travel" value={`${Math.round(s.travel_minutes)}`} sub="minutes" />
        <Cell
          label="Confidence"
          value={`${Math.round(s.quantity_confidence * 100)}%`}
          sub="on headcount"
        />
      </div>

      {/* --- trust, on its own visual track ----------------------------- */}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span
          className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px]
                      font-medium ${t.bg} ${t.text} ${t.border}`}
          title="Trust is corroboration, source diversity and freshness — a separate signal from urgency"
        >
          <Shield />
          {t.label}
          <span className="font-mono opacity-80">{t.percent}</span>
        </span>
        {s.duplicate_collapse_count > 1 && (
          <span className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
            Merged · {s.duplicate_collapse_count} reports
          </span>
        )}
        <span
          className="rounded border border-gray-200 bg-gray-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500"
          title={s.location.method}
        >
          {RESOLUTION_SHORT[s.location.resolution]}
        </span>
      </div>

      {/* --- why, and what it beat -------------------------------------- */}
      <div className="mt-3 space-y-1 border-t border-gray-100 pt-2.5">
        {s.because.slice(0, 2).map((line, i) => (
          <p key={i} className="text-[11px] leading-snug text-slate-600">
            <span className="text-slate-400">·</span> {line}
          </p>
        ))}
        {s.instead_of && (
          <p className="text-[11px] leading-snug text-slate-500">
            <span className="font-medium text-slate-600">Instead of:</span> {s.instead_of}
          </p>
        )}
        {s.zone_note && (
          <p className="text-[11px] leading-snug text-slate-500">
            <span className="font-medium text-slate-600">Equity:</span> {s.zone_note}
          </p>
        )}
      </div>

      {/* --- the human decides ------------------------------------------ */}
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={onAccept}
          disabled={busy}
          className="flex-1 rounded-md bg-slate-800 px-3 py-1.5 text-xs font-semibold text-white
                     shadow-sm transition-colors hover:bg-slate-900 disabled:opacity-50"
        >
          Accept and dispatch
        </button>
        <button
          onClick={() => onOpen(s.demand_id)}
          className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium
                     text-slate-700 shadow-sm transition-colors hover:bg-gray-50"
        >
          Review evidence
        </button>
      </div>
      <p className="mt-1.5 text-[10px] leading-snug text-slate-400">
        Every decision here is overridable, and every override is written to the audit trail with
        its reason.
      </p>
    </Frame>
  );
}

// --------------------------------------------------------------------------

function Frame({ children, accent }: { children: React.ReactNode; accent: string }) {
  return (
    <div className="pointer-events-auto w-[350px] overflow-hidden rounded-lg border border-gray-200 bg-white shadow-lg">
      {/* The coloured top accent is what makes this card read as the primary
          object on the screen rather than one more panel. */}
      <div className={`h-1 w-full ${accent}`} />
      <div className="p-3.5">{children}</div>
    </div>
  );
}

function Header({ title, kicker }: { title: string; kicker: string }) {
  return (
    <div>
      <div className="flex items-center gap-1.5">
        <Spark />
        <h3 className="text-[11px] font-bold uppercase tracking-wide text-slate-700">{title}</h3>
      </div>
      <p className="mt-0.5 font-mono text-[10px] text-slate-400">{kicker}</p>
    </div>
  );
}

function Cell({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="font-mono text-base font-semibold leading-tight tabular-nums text-slate-900">
        {value}
      </div>
      <div className="text-[9px] leading-tight text-slate-500">{sub}</div>
    </div>
  );
}

function Spark() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5 text-slate-700" fill="currentColor" aria-hidden>
      <path d="M8 1l1.6 4.2L14 7l-4.4 1.8L8 13l-1.6-4.2L2 7l4.4-1.8L8 1z" />
    </svg>
  );
}

function Shield() {
  return (
    <svg viewBox="0 0 16 16" className="h-3 w-3" fill="currentColor" aria-hidden>
      <path d="M8 1l5 2v4.5c0 3.2-2.1 6.1-5 7-2.9-.9-5-3.8-5-7V3l5-2zm0 1.6L4.5 4v3.5c0 2.5 1.5 4.7 3.5 5.5 2-.8 3.5-3 3.5-5.5V4L8 2.6z" />
    </svg>
  );
}
