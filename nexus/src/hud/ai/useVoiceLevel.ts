'use client';

import { useEffect, useRef, useState } from 'react';
import { voice } from '@/stores/runtime';

/**
 * Speech amplitude for the DOM.
 *
 * The runtime carries the envelope at frame rate; React needs it far less
 * often. Sampling at 20 Hz and quantising to 24 steps means the meter only
 * re-renders when a bar would actually change, which is roughly a tenth as
 * often as a naive rAF subscription.
 */
export function useVoiceLevel(steps = 24): number {
  const [level, setLevel] = useState(0);
  const raf = useRef(0);
  const last = useRef(0);

  useEffect(() => {
    let previous = -1;
    const tick = (now: number) => {
      raf.current = requestAnimationFrame(tick);
      if (now - last.current < 50) return;
      last.current = now;
      const quantised = Math.round(voice.level * steps) / steps;
      if (quantised !== previous) {
        previous = quantised;
        setLevel(quantised);
      }
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [steps]);

  return level;
}
