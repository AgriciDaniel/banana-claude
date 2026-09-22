'use client';

import type { CalendarData, ModuleFeed } from '@/modules/types';
import { FeedState, Line, Provenance, Section } from './shared';
import { useLocaleTag, useT } from '@/i18n';

/** Today, then the rest of the fortnight. */
export function CalendarPanel({ feed }: { feed: ModuleFeed<CalendarData> }) {
  const t = useT();
  const tag = useLocaleTag();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  const endOfDay = new Date();
  endOfDay.setHours(23, 59, 59, 999);
  const today = d.events.filter((e) => e.start <= endOfDay.getTime());
  const later = d.events.filter((e) => e.start > endOfDay.getTime());

  const time = (ms: number) =>
    new Date(ms).toLocaleTimeString(tag, { hour: '2-digit', minute: '2-digit' });
  const day = (ms: number) =>
    new Date(ms).toLocaleDateString(tag, { weekday: 'short', day: 'numeric', month: 'short' });

  return (
    <div>
      <Section title={t('calendar.summary')}>
        <Line label={t('calendar.today')} value={String(d.todayCount)} />
        <Line
          label={t('calendar.conflicts')}
          value={String(d.conflicts)}
          tone={d.conflicts > 0 ? 'warn' : 'good'}
        />
        <Line
          label={t('calendar.free')}
          value={`${Math.floor(d.freeMinutes / 60)}h ${d.freeMinutes % 60}m`}
        />
      </Section>

      <Section title={t('calendar.todayList')}>
        {today.length === 0 && (
          <p className="font-mono text-[10px] text-ghost">{t('calendar.clear')}</p>
        )}
        {today.map((event) => (
          <div key={event.id} className="border-b border-signal/8 py-[6px] last:border-0">
            <div className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-lumen">
                {event.title}
              </span>
              <span className="shrink-0 font-mono text-[9.5px] text-signal">
                {event.allDay ? t('calendar.allDay') : time(event.start)}
              </span>
            </div>
            {event.location && (
              <p className="mt-0.5 truncate font-mono text-[9px] text-ghost">{event.location}</p>
            )}
          </div>
        ))}
      </Section>

      {later.length > 0 && (
        <Section title={t('calendar.ahead')}>
          {later.slice(0, 8).map((event) => (
            <div key={event.id} className="flex items-baseline justify-between gap-3 py-[3px]">
              <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-ghost">
                {event.title}
              </span>
              <span className="shrink-0 font-mono text-[9px] text-ghost/80">{day(event.start)}</span>
            </div>
          ))}
        </Section>
      )}

      <Provenance feed={feed} />
    </div>
  );
}
