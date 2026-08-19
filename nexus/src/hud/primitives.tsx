'use client';

import type { ReactNode } from 'react';
import { motion } from 'framer-motion';

/**
 * HUD primitives.
 *
 * Four components carry the entire interface. If a fifth is ever needed, the
 * right question is usually whether the new panel is really different or just
 * differently arranged.
 */

export function Panel({
  children,
  className = '',
  delay = 0,
  from = 'left',
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  from?: 'left' | 'right';
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: from === 'left' ? -14 : 14, filter: 'blur(6px)' }}
      animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={{ opacity: 0, x: from === 'left' ? -14 : 14, filter: 'blur(6px)' }}
      transition={{ duration: 0.7, delay, ease: [0.16, 1, 0.3, 1] }}
      className={`hud-panel hud-ticks relative px-3.5 py-3 ${className}`}
    >
      {children}
    </motion.div>
  );
}

export function Row({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: ReactNode;
  tone?: 'default' | 'good' | 'warn' | 'muted';
}) {
  const color =
    tone === 'good'
      ? 'text-lock'
      : tone === 'warn'
        ? 'text-ember'
        : tone === 'muted'
          ? 'text-ghost'
          : 'text-lumen';
  return (
    <div className="flex items-baseline justify-between gap-6 py-[3px]">
      <span className="hud-label">{label}</span>
      <span className={`hud-value ${color}`}>{value}</span>
    </div>
  );
}

/** Segmented meter. Same visual language as the bars painted on the cards. */
export function Meter({
  value,
  segments = 16,
  tone = 'signal',
}: {
  value: number;
  segments?: number;
  tone?: 'signal' | 'ember' | 'lock';
}) {
  const lit = Math.round(Math.max(0, Math.min(1, value)) * segments);
  const color =
    tone === 'ember' ? 'bg-ember' : tone === 'lock' ? 'bg-lock' : 'bg-signal';
  return (
    <div className="flex items-center gap-[3px]" aria-hidden>
      {Array.from({ length: segments }, (_, i) => (
        <span
          key={i}
          className={`h-[7px] w-[3px] rounded-[1px] transition-colors duration-150 ${
            i < lit ? color : 'bg-lumen/10'
          }`}
        />
      ))}
    </div>
  );
}

export function Divider() {
  return <div className="my-2 h-px bg-signal/12" />;
}

/** Live status pip. Pulses only while genuinely live — a lying light is worse
    than no light. */
export function Pip({ tone = 'good', pulse = true }: { tone?: 'good' | 'warn' | 'idle'; pulse?: boolean }) {
  const color = tone === 'good' ? 'bg-lock' : tone === 'warn' ? 'bg-ember' : 'bg-ghost';
  return (
    <span className="relative inline-flex h-1.5 w-1.5">
      {pulse && tone !== 'idle' && (
        <motion.span
          className={`absolute inline-flex h-full w-full rounded-full ${color}`}
          animate={{ opacity: [0.9, 0.1, 0.9], scale: [1, 2.1, 1] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
        />
      )}
      <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${color}`} />
    </span>
  );
}
