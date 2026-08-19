'use client';

import type { Fixture, ModuleFeed, SportsData } from '@/modules/types';
import { FeedState, Provenance, Section } from './shared';
import { useT } from '@/i18n';

function Row({ fixture }: { fixture: Fixture }) {
  const played = fixture.homeScore !== null && fixture.awayScore !== null;
  const homeWon = played && fixture.homeScore! > fixture.awayScore!;
  const awayWon = played && fixture.awayScore! > fixture.homeScore!;

  return (
    <div className="flex items-center gap-2 border-b border-signal/8 py-[6px] last:border-0">
      <div className="min-w-0 flex-1">
        <p className={`truncate font-mono text-[10px] ${homeWon ? 'text-lumen' : 'text-ghost'}`}>
          {fixture.home}
        </p>
        <p className={`truncate font-mono text-[10px] ${awayWon ? 'text-lumen' : 'text-ghost'}`}>
          {fixture.away}
        </p>
      </div>

      {played ? (
        <div className="text-right">
          <p className={`hud-value ${homeWon ? 'text-lumen' : 'text-ghost'}`}>{fixture.homeScore}</p>
          <p className={`hud-value ${awayWon ? 'text-lumen' : 'text-ghost'}`}>{fixture.awayScore}</p>
        </div>
      ) : (
        <span className="font-mono text-[9px] tracking-[0.12em] text-ghost">
          {fixture.date.slice(5)}
        </span>
      )}

      {fixture.status === 'live' && (
        <span className="ml-1 h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-ember" />
      )}
    </div>
  );
}

/** Results, fixtures and the table. */
export function SportsPanel({ feed }: { feed: ModuleFeed<SportsData> }) {
  const t = useT();
  const gate = FeedState({ feed });
  if (gate) return gate;
  const d = feed.data!;

  return (
    <div>
      <p className="font-mono text-[10px] tracking-[0.18em] text-signal">
        {d.league.toUpperCase()}
      </p>

      {d.recent.length > 0 && (
        <Section title={t('sports.results')}>
          {d.recent.slice(0, 5).map((f) => (
            <Row key={f.id} fixture={f} />
          ))}
        </Section>
      )}

      {d.upcoming.length > 0 && (
        <Section title={t('sports.fixtures')}>
          {d.upcoming.slice(0, 5).map((f) => (
            <Row key={f.id} fixture={f} />
          ))}
        </Section>
      )}

      {d.standings.length > 0 && (
        <Section title={t('sports.table')}>
          {d.standings.map((row) => (
            <div key={row.team} className="flex items-center gap-2 py-[3px]">
              <span className="w-4 font-mono text-[9px] text-ghost">{row.rank}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-lumen">
                {row.team}
              </span>
              <span className="w-7 text-right font-mono text-[9px] text-ghost">{row.played}</span>
              <span
                className={`w-8 text-right font-mono text-[9px] ${
                  row.goalDiff > 0 ? 'text-lock' : row.goalDiff < 0 ? 'text-ember' : 'text-ghost'
                }`}
              >
                {row.goalDiff > 0 ? `+${row.goalDiff}` : row.goalDiff}
              </span>
              <span className="w-6 text-right hud-value">{row.points}</span>
            </div>
          ))}
        </Section>
      )}

      <Provenance feed={feed} />
    </div>
  );
}
