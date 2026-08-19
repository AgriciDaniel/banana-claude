'use client';

import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useSystemStore } from '@/stores/useSystemStore';
import { useT, type TranslationKey } from '@/i18n';

/** [key label, action label]. A literal string is a key cap, not a phrase. */
type Entry = [TranslationKey | { literal: string }, TranslationKey];

const HAND_KEYS: Entry[] = [
  ['legend.swipe', 'legend.swipe.do'],
  ['legend.pinch', 'legend.pinch.do'],
  ['legend.release', 'legend.release.do'],
  ['legend.depth', 'legend.depth.do'],
  ['legend.palm', 'legend.palm.do'],
  ['legend.circle', 'legend.circle.do'],
];

const POINTER_KEYS: Entry[] = [
  [{ literal: '← →' }, 'legend.arrows.do'],
  ['legend.drag', 'legend.drag.do'],
  ['legend.space', 'legend.space.do'],
  [{ literal: 'F' }, 'legend.f.do'],
  [{ literal: 'D' }, 'legend.d.do'],
  [{ literal: 'H' }, 'legend.h.do'],
];

/**
 * Centre-bottom legend.
 *
 * Shown for the first stretch of a session and then retired — a gesture
 * vocabulary needs teaching once, and permanent on-screen instructions are an
 * admission that the interaction was never learnable.
 */
export function GestureLegend() {
  const input = useSystemStore((s) => s.input);
  const t = useT();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const id = window.setTimeout(() => setVisible(false), 14000);
    return () => window.clearTimeout(id);
  }, []);

  const keys = input === 'hand' ? HAND_KEYS : POINTER_KEYS;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 10, filter: 'blur(6px)' }}
          transition={{ duration: 0.8, delay: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="absolute bottom-7 left-1/2 flex -translate-x-1/2 items-center gap-5"
        >
          {keys.map(([key, action]) => {
            const cap = typeof key === 'string' ? t(key) : key.literal;
            return (
              <div key={action} className="flex flex-col items-center gap-1">
                <span className="font-mono text-[10px] tracking-[0.18em] text-lumen/85">{cap}</span>
                <span className="font-mono text-[8.5px] tracking-[0.14em] text-ghost/70">
                  {t(action)}
                </span>
              </div>
            );
          })}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
