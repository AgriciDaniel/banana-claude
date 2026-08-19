'use client';

import { motion } from 'framer-motion';
import type { ModuleFeed, MusicData } from '@/modules/types';
import { FeedState, Line, Provenance, Section } from './shared';
import { useT } from '@/i18n';

/**
 * A spectrum analyser, not a player.
 *
 * There is no track and no library to connect to, so rather than a fake
 * now-playing card this shows what the environment is genuinely emitting: the
 * ambient pad, the sub drone, the air layer and the assistant's voice, read
 * straight off the master bus.
 */
export function MusicPanel({ feed }: { feed: ModuleFeed<MusicData> }) {
  const t = useT();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const peak = Math.max(...d.spectrum, 0);

  return (
    <div>
      <Section title={t('music.spectrum')}>
        <div className="flex h-[76px] items-end gap-[2px]" aria-hidden>
          {d.spectrum.map((band, i) => (
            <motion.span
              key={i}
              className="flex-1 rounded-t-[1px] bg-signal"
              style={{ opacity: 0.35 + band * 0.65 }}
              animate={{ height: `${Math.max(2, band * 100)}%` }}
              transition={{ duration: 0.09, ease: 'linear' }}
            />
          ))}
        </div>
        <div className="mt-1 flex justify-between font-mono text-[8.5px] tracking-[0.1em] text-ghost/70">
          <span>40 Hz</span>
          <span>1 kHz</span>
          <span>16 kHz</span>
        </div>
      </Section>

      <Section title={t('music.output')}>
        <Line
          label={t('music.level')}
          value={peak > 0.02 ? `${Math.round(d.level * 100)}%` : t('music.silent')}
          tone={d.playing ? 'good' : 'muted'}
        />
      </Section>

      <Section title={t('music.sources')}>
        {d.sources.length === 0 && (
          <p className="font-mono text-[10px] text-ghost">{t('music.silent')}</p>
        )}
        {d.sources.map((source) => (
          <div key={source} className="flex items-center gap-2 py-[3px]">
            <span className="h-1 w-1 rounded-full bg-lock" />
            <span className="font-mono text-[10px] text-lumen">{source}</span>
          </div>
        ))}
      </Section>

      <p className="mt-1 font-mono text-[9px] leading-[15px] tracking-[0.1em] text-signal/70">
        {t('music.note')}
      </p>
      <Provenance feed={feed} />
    </div>
  );
}
