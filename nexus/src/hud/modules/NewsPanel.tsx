'use client';

import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { Article, ModuleFeed, NewsData } from '@/modules/types';
import { FeedState, Provenance, Section } from './shared';
import { useT } from '@/i18n';
import { getAudio } from '@/audio/AudioEngine';

/**
 * News as a deck.
 *
 * Articles stack and are swiped through rather than listed, because a list of
 * eighteen headlines in a 330px rail is a scrollbar, and a deck is a thing you
 * flick. Drag past the threshold or use the arrows; both advance the same
 * index, so the interaction is discoverable without being mandatory.
 */

const relative = (ts: number): string => {
  const mins = Math.round((Date.now() - ts) / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
};

export function NewsPanel({ feed }: { feed: ModuleFeed<NewsData> }) {
  const t = useT();
  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState(1);

  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;
  if (d.articles.length === 0) return null;

  const advance = (step: number) => {
    setDirection(step);
    setIndex((i) => (i + step + d.articles.length) % d.articles.length);
    getAudio().tick(step * 0.4);
  };

  const article = d.articles[index]!;
  // The two behind form the visible stack.
  const behind = [1, 2].map((offset) => d.articles[(index + offset) % d.articles.length]!);

  return (
    <div>
      {d.digest && (
        <Section title={t('news.digest')}>
          <p className="font-sans text-[12px] leading-[19px] text-lumen/90">{d.digest}</p>
        </Section>
      )}

      <Section title={`${t('news.stories')} · ${index + 1}/${d.articles.length}`}>
        <div className="relative h-[186px] select-none">
          {/* Stack shadows, drawn back to front. */}
          {behind.map((a, i) => (
            <div
              key={`${a.id}-behind`}
              className="hud-panel absolute inset-x-0 top-0 h-[150px] rounded-sm"
              style={{
                transform: `translateY(${(i + 1) * 7}px) scale(${1 - (i + 1) * 0.035})`,
                opacity: 0.4 - i * 0.15,
              }}
              aria-hidden
            />
          ))}

          <AnimatePresence initial={false} custom={direction} mode="popLayout">
            <motion.article
              key={article.id}
              custom={direction}
              drag="x"
              dragConstraints={{ left: 0, right: 0 }}
              dragElastic={0.28}
              onDragEnd={(_, info) => {
                if (Math.abs(info.offset.x) > 70) advance(info.offset.x < 0 ? 1 : -1);
              }}
              initial={{ opacity: 0, x: direction * 60, rotate: direction * 2 }}
              animate={{ opacity: 1, x: 0, rotate: 0 }}
              exit={{ opacity: 0, x: direction * -90, rotate: direction * -3 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              className="hud-panel absolute inset-x-0 top-0 cursor-grab p-3 active:cursor-grabbing"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[9px] tracking-[0.16em] text-signal">
                  {article.source.toUpperCase()}
                </span>
                <span className="font-mono text-[9px] tracking-[0.14em] text-ghost">
                  {relative(article.published)}
                </span>
              </div>

              <h4 className="mt-2 font-sans text-[13px] font-medium leading-[18px] text-lumen">
                {article.title}
              </h4>

              <p className="mt-1.5 line-clamp-3 font-mono text-[9.5px] leading-[15px] text-ghost">
                {article.summary}
              </p>

              {article.link && (
                <a
                  href={article.link}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="mt-2 inline-block font-mono text-[9px] tracking-[0.18em] text-ghost transition-colors hover:text-signal"
                >
                  {t('news.open')}
                </a>
              )}
            </motion.article>
          </AnimatePresence>
        </div>

        <div className="mt-1 flex items-center justify-between">
          <button
            type="button"
            onClick={() => advance(-1)}
            className="font-mono text-[10px] tracking-[0.2em] text-ghost transition-colors hover:text-signal"
          >
            {'\u2190'}
          </button>
          <span className="font-mono text-[9px] tracking-[0.16em] text-ghost/70">
            {t('news.swipe')}
          </span>
          <button
            type="button"
            onClick={() => advance(1)}
            className="font-mono text-[10px] tracking-[0.2em] text-ghost transition-colors hover:text-signal"
          >
            {'\u2192'}
          </button>
        </div>
      </Section>

      <Provenance feed={feed} />
    </div>
  );
}
