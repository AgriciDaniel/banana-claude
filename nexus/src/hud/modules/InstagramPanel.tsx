'use client';

import type { InstagramData, ModuleFeed } from '@/modules/types';
import { Bar, FeedState, Line, Provenance, Section, Spark } from './shared';
import { useT } from '@/i18n';

const compact = (n: number) =>
  n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n);

/** Audience, reach, growth and top content. */
export function InstagramPanel({ feed }: { feed: ModuleFeed<InstagramData> }) {
  const t = useT();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const growth = d.growth.map((g) => g.value);
  const netGrowth = growth.reduce((sum, v) => sum + v, 0);

  return (
    <div>
      <div className="flex items-end justify-between">
        <span className="font-sans text-[30px] font-extralight leading-none text-lumen">
          {compact(d.followers)}
        </span>
        <p className="font-mono text-[10px] tracking-[0.14em] text-signal">@{d.username}</p>
      </div>

      <Section title={t('instagram.audience')}>
        <Line label={t('instagram.followers')} value={d.followers.toLocaleString('en-US')} />
        <Line label={t('instagram.following')} value={compact(d.follows)} tone="muted" />
        <Line label={t('instagram.posts')} value={String(d.posts)} tone="muted" />
        <Line label={t('instagram.reels')} value={String(d.reels)} tone="muted" />
      </Section>

      <Section title={t('instagram.reach')}>
        <Line label={t('instagram.reached')} value={compact(d.reach)} />
        <Line label={t('instagram.impressions')} value={compact(d.impressions)} tone="muted" />
        <Line label={t('instagram.views')} value={compact(d.profileViews)} tone="muted" />
        <Line
          label={t('instagram.engagement')}
          value={`${d.engagementRate.toFixed(2)}%`}
          tone={d.engagementRate >= 3 ? 'good' : 'default'}
        />
        <div className="py-1">
          <Bar value={d.engagementRate / 10} tone={d.engagementRate >= 3 ? 'lock' : 'signal'} />
        </div>
      </Section>

      {growth.length > 1 && (
        <Section title={t('instagram.growth')}>
          <Spark values={growth} tone={netGrowth >= 0 ? 'lock' : 'ember'} />
          <Line
            label={t('instagram.net')}
            value={`${netGrowth >= 0 ? '+' : ''}${netGrowth}`}
            tone={netGrowth >= 0 ? 'good' : 'warn'}
          />
        </Section>
      )}

      {d.top.length > 0 && (
        <Section title={t('instagram.top')}>
          {d.top.map((post) => (
            <a
              key={post.id}
              href={post.permalink}
              target="_blank"
              rel="noreferrer noopener"
              className="group flex items-center gap-2 border-b border-signal/8 py-2 last:border-0"
            >
              {post.url && (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={post.url}
                  alt=""
                  className="h-10 w-10 shrink-0 border border-signal/20 object-cover"
                />
              )}
              <span className="min-w-0 flex-1 truncate font-mono text-[9.5px] text-ghost transition-colors group-hover:text-lumen">
                {post.caption || post.mediaType}
              </span>
              <span className="shrink-0 font-mono text-[9px] text-signal">
                {compact(post.likes)} {'\u2661'}
              </span>
            </a>
          ))}
        </Section>
      )}

      <Provenance feed={feed} />
    </div>
  );
}
