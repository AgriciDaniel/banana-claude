'use client';

import type { ModuleFeed, YoutubeData } from '@/modules/types';
import { useT } from '@/i18n';
import { FeedState, Line, Provenance, Section } from './shared';

/**
 * The channel, as figures worth acting on.
 *
 * Subscriber count is shown because people ask for it, but it is not the
 * headline. Views per subscriber is: below about 0.2 the channel is only
 * reaching the people who already follow it, which is the state a growing
 * channel has to leave. That number gets the emphasis and the colour.
 */
function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}K`;
  return String(value);
}

export function YoutubePanel({ feed }: { feed: ModuleFeed<YoutubeData> }) {
  const t = useT();

  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const ratio = d.subscribers > 0 ? d.recentAverage / d.subscribers : 0;
  const reaching = ratio >= 0.2;
  const best = [...d.videos].sort((a, b) => b.views - a.views).slice(0, 3);

  return (
    <div>
      <div className="pb-3">
        <p className="font-mono text-[10px] tracking-[0.2em] text-ghost">{d.handle || d.title}</p>
        <p className="mt-1 text-[34px] leading-none text-lumen">{compact(d.subscribers)}</p>
        <p className="mt-1 font-mono text-[10px] tracking-[0.14em] text-ghost">
          {t('youtube.subscribers')}
        </p>
      </div>

      <Section title={t('youtube.reach')}>
        <Line
          label={t('youtube.perSubscriber')}
          value={ratio.toFixed(2)}
          tone={reaching ? 'good' : 'warn'}
        />
        <Line label={t('youtube.averageViews')} value={compact(d.recentAverage)} />
        <Line label={t('youtube.videos')} value={String(d.videoCount)} />
        <Line label={t('youtube.shorts')} value={`${Math.round(d.shortsShare * 100)}%`} />
      </Section>

      {best.length > 0 && (
        <Section title={t('youtube.best')}>
          {best.map((v) => (
            <div key={v.id} className="flex items-center gap-2.5 border-b border-signal/8 py-2 last:border-0">
              {v.thumbnail && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`/api/media?url=${encodeURIComponent(v.thumbnail)}`}
                  alt=""
                  className="h-8 w-14 flex-none rounded-[2px] object-cover"
                />
              )}
              <span className="min-w-0 flex-1 truncate text-[11px] text-lumen">{v.title}</span>
              <span className="hud-value flex-none text-ghost">{compact(v.views)}</span>
            </div>
          ))}
        </Section>
      )}

      <Provenance feed={feed} />
    </div>
  );
}
