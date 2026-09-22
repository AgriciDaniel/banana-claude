import type { Fixture, ModuleFeed, SportsData, StandingRow } from '@/modules/types';

/**
 * Sports, from TheSportsDB.
 *
 * The free tier's shared test key covers past results, upcoming fixtures and
 * the league table, which is exactly the three things the module shows. Set
 * NEXUS_SPORTSDB_KEY for a personal key, and NEXUS_LEAGUE_ID to follow a
 * different competition (4328 is the English Premier League).
 */

const BASE = 'https://www.thesportsdb.com/api/v1/json';

const key = () => process.env.NEXUS_SPORTSDB_KEY ?? '3';
const leagueId = () => process.env.NEXUS_LEAGUE_ID ?? '4328';

interface RawEvent {
  idEvent: string;
  strHomeTeam: string;
  strAwayTeam: string;
  intHomeScore: string | null;
  intAwayScore: string | null;
  dateEvent: string;
  strTime?: string | null;
  strLeague: string;
  strStatus?: string | null;
}

interface RawStanding {
  intRank: string;
  strTeam: string;
  intPlayed: string;
  intPoints: string;
  intGoalDifference: string;
  strForm?: string | null;
}

async function get<T>(path: string, signal: AbortSignal): Promise<T | null> {
  try {
    const response = await fetch(`${BASE}/${key()}/${path}`, { signal, next: { revalidate: 300 } });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

function toFixture(event: RawEvent, status: Fixture['status']): Fixture {
  const home = event.intHomeScore === null ? null : Number(event.intHomeScore);
  const away = event.intAwayScore === null ? null : Number(event.intAwayScore);
  const live = event.strStatus && /1H|2H|HT|LIVE/i.test(event.strStatus);
  return {
    id: event.idEvent,
    home: event.strHomeTeam,
    away: event.strAwayTeam,
    homeScore: Number.isFinite(home as number) ? home : null,
    awayScore: Number.isFinite(away as number) ? away : null,
    date: event.strTime ? `${event.dateEvent} ${event.strTime.slice(0, 5)}` : event.dateEvent,
    status: live ? 'live' : status,
    league: event.strLeague,
  };
}

export async function fetchSports(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<SportsData>> {
  const id = leagueId();
  const [past, next, table] = await Promise.all([
    get<{ events: RawEvent[] | null }>(`eventspastleague.php?id=${id}`, signal),
    get<{ events: RawEvent[] | null }>(`eventsnextleague.php?id=${id}`, signal),
    get<{ table: RawStanding[] | null }>(`lookuptable.php?l=${id}`, signal),
  ]);

  const recent = (past?.events ?? []).slice(0, 8).map((e) => toFixture(e, 'finished'));
  const upcoming = (next?.events ?? []).slice(0, 8).map((e) => toFixture(e, 'upcoming'));
  const standings: StandingRow[] = (table?.table ?? []).slice(0, 12).map((row) => ({
    rank: Number(row.intRank),
    team: row.strTeam,
    played: Number(row.intPlayed),
    points: Number(row.intPoints),
    goalDiff: Number(row.intGoalDifference),
    form: row.strForm ?? undefined,
  }));

  if (recent.length === 0 && upcoming.length === 0 && standings.length === 0) {
    throw new Error('TheSportsDB returned nothing for this league');
  }

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: 'TheSportsDB',
    data: {
      league: recent[0]?.league ?? upcoming[0]?.league ?? `League ${id}`,
      recent,
      upcoming,
      standings,
    },
  };
}
