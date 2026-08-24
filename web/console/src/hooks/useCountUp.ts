/**
 * Animates a displayed integer toward a target value instead of snapping.
 *
 * A metrics strip whose numbers jump straight to their new value on every
 * tick reads as a page refresh. Tweening them over a few hundred milliseconds
 * is what makes "messages ingested" and "demand records" look like they are
 * being counted rather than looked up - cheap to add, and it is most of what
 * makes the bottom bar feel alive during Play.
 */

import { useEffect, useRef, useState } from "react";

const DURATION_MS = 550;

export function useCountUp(target: number): number {
  const [value, setValue] = useState(target);
  const from = useRef(target);
  const start = useRef<number | null>(null);
  const frame = useRef<number>();

  useEffect(() => {
    if (target === from.current) return;
    from.current = value;
    start.current = null;
    cancelAnimationFrame(frame.current!);

    const step = (t: number) => {
      if (start.current === null) start.current = t;
      const elapsed = t - start.current;
      const p = Math.min(1, elapsed / DURATION_MS);
      // Ease-out: fast at first, settles gently on the target - reads as a
      // counter catching up, not a linear slide.
      const eased = 1 - (1 - p) * (1 - p);
      const next = Math.round(from.current + (target - from.current) * eased);
      setValue(next);
      if (p < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current!);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return value;
}
