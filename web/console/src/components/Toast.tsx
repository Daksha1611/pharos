/**
 * A single ephemeral confirmation of what a control just did.
 *
 * Buttons that only flicker to "…" and back give a judge nothing to point
 * at - the plan changed somewhere on the map, but nothing on screen says so
 * in words. This says so: "Bridge collapsed - 4 crossings still standing"
 * appears where the eye already is (top of screen, under the controls that
 * caused it) and fades on its own.
 */

export type ToastTone = "default" | "success" | "warn" | "danger";

export interface ToastData {
  id: number;
  text: string;
  tone: ToastTone;
}

const TONE = {
  default: "border-slate-300 bg-slate-800 text-white",
  success: "border-emerald-300 bg-emerald-600 text-white",
  warn: "border-amber-300 bg-amber-500 text-white",
  danger: "border-red-300 bg-red-600 text-white",
} as const;

export function Toast({ toast }: { toast: ToastData | null }) {
  if (!toast) return null;
  return (
    <div className="pointer-events-none absolute inset-x-0 top-3 z-30 flex justify-center">
      <div
        key={toast.id}
        className={`pointer-events-auto animate-toast-in rounded-full border px-4 py-2 text-xs
                    font-medium shadow-lg ${TONE[toast.tone]}`}
      >
        {toast.text}
      </div>
    </div>
  );
}
