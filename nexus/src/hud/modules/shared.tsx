'use client';

import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import type { ModuleFeed } from '@/modules/types';
import { useT } from '@/i18n';

/**
 * Panel primitives.
 *
 * Ten modules with ten bespoke layouts would drift apart within a week. These
 * are the shared parts: a section heading, a keyed row, a bar, a sparkline and
 * the three non-content states every feed can be in.
 */

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="py-2">
      <h3 className="hud-label mb-1.5">{title}</h3>
      {children}
    </section>
  );
}

export function Line({
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
    <div className="flex items-baseline justify-between gap-4 py-[3px]">
      <span className="font-mono text-[10px] tracking-[0.1em] text-ghost">{label}</span>
      <span className={`hud-value ${color}`}>{value}</span>
    </div>
  );
}

/** Proportional bar. Width is the only encoding — no gradients, no labels. */
export function Bar({ value, tone = 'signal' }: { value: number; tone?: 'signal' | 'ember' | 'lock' }) {
  const color = tone === 'ember' ? 'bg-ember' : tone === 'lock' ? 'bg-lock' : 'bg-signal';
  return (
    <div className="h-[3px] w-full overflow-hidden rounded-full bg-lumen/8">
      <motion.div
        className={`h-full rounded-full ${color}`}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  );
}

/**
 * Inline sparkline. Drawn as an SVG path rather than a chart library because
 * it is forty points in a fixed box and nothing else is needed.
 */
export function Spark({
  values,
  tone = 'signal',
  height = 30,
}: {
  values: number[];
  tone?: 'signal' | 'ember' | 'lock';
  height?: number;
}) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stroke = tone === 'ember' ? 'stroke-ember' : tone === 'lock' ? 'stroke-lock' : 'stroke-signal';

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * 100;
      const y = height - ((v - min) / span) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" className="h-[30px] w-full" aria-hidden>
      <motion.polyline
        points={points}
        fill="none"
        strokeWidth={1.2}
        vectorEffect="non-scaling-stroke"
        className={stroke}
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ duration: 0.9, ease: 'easeOut' }}
      />
    </svg>
  );
}

/**
 * Loading, fault and setup states.
 *
 * Returns null when there is data to draw, so a panel body is simply:
 *   const gate = <FeedState feed={feed} />; if (gate) return gate;
 */
export function FeedState({ feed }: { feed: ModuleFeed<unknown> }) {
  const t = useT();

  if (feed.status === 'unconfigured') {
    return (
      <div className="py-3">
        <p className="font-mono text-[10px] tracking-[0.2em] text-signal">{t('module.setup')}</p>
        <p className="mt-2 font-mono text-[10px] leading-[17px] tracking-[0.06em] text-ghost">
          {feed.setupHint}
        </p>
      </div>
    );
  }

  if (feed.status === 'error' || (!feed.data && feed.status !== 'loading' && feed.status !== 'idle')) {
    return (
      <div className="py-3">
        <p className="font-mono text-[10px] tracking-[0.2em] text-ember">{t('module.unavailable')}</p>
        <p className="mt-2 font-mono text-[10px] leading-[17px] tracking-[0.06em] text-ghost">
          {feed.error}
        </p>
      </div>
    );
  }

  if (!feed.data) {
    return (
      <div className="flex items-center gap-2 py-4">
        <motion.span
          className="inline-block h-1 w-1 rounded-full bg-signal"
          animate={{ opacity: [1, 0.2, 1] }}
          transition={{ duration: 1.1, repeat: Infinity }}
        />
        <span className="font-mono text-[10px] tracking-[0.2em] text-ghost">{t('module.loading')}</span>
      </div>
    );
  }

  return null;
}

/** Provenance footer. Every panel ends with one. */
export function Provenance({ feed }: { feed: ModuleFeed<unknown> }) {
  const t = useT();
  if (!feed.source) return null;
  const age = feed.fetchedAt ? Math.round((Date.now() - feed.fetchedAt) / 1000) : null;
  return (
    <p className="mt-1 font-mono text-[9px] tracking-[0.14em] text-ghost/70">
      {t('module.source')}: {feed.source}
      {age !== null && age < 86400 ? ` · ${age < 90 ? `${age}s` : `${Math.round(age / 60)}m`}` : ''}
      {feed.status === 'stale' ? ` · ${t('module.stale')}` : ''}
    </p>
  );
}
