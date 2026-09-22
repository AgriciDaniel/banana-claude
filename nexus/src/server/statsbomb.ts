/**
 * StatsBomb Open Data.
 *
 * The only source at this depth that is genuinely free to use: real event
 * data, with StatsBomb's own xG on every shot, published under CC BY-NC-SA.
 * Non-commercial, and attribution is a condition -- every figure that leaves
 * here carries the credit, and the tool result tells the model to keep it.
 *
 * The limits are worth stating plainly. Coverage is competitions StatsBomb
 * chose to open, not the current season, so this answers "what did he
 * actually do in that match" and never "how is he playing this week". And an
 * event file is a couple of megabytes, so work is done one match at a time
 * rather than by aggregating a season on demand.
 */

const RAW = 'https://raw.githubusercontent.com/statsbomb/open-data/master/data';

export const STATSBOMB_CREDIT = 'StatsBomb Open Data (CC BY-NC-SA)';

interface CompetitionEntry {
  competition_id: number;
  season_id: number;
  competition_name: string;
  season_name: string;
  country_name?: string;
}

interface MatchEntry {
  match_id: number;
  match_date: string;
  home_score: number;
  away_score: number;
  home_team: { home_team_name: string };
  away_team: { away_team_name: string };
  competition: { competition_name: string };
  season: { season_name: string };
  competition_stage?: { name?: string };
}

interface EventEntry {
  id: string;
  type: { name: string };
  player?: { id: number; name: string };
  team?: { name: string };
  location?: number[];
  pass?: {
    outcome?: { name: string };
    end_location?: number[];
    shot_assist?: boolean;
    goal_assist?: boolean;
  };
  shot?: {
    statsbomb_xg?: number;
    outcome?: { name: string };
    key_pass_id?: string;
  };
  carry?: { end_location?: number[] };
  duel?: { outcome?: { name: string } };
  dribble?: { outcome?: { name: string } };
}

async function fetchJson<T>(path: string, signal: AbortSignal): Promise<T | null> {
  const response = await fetch(`${RAW}/${path}`, {
    signal,
    headers: {
      accept: 'application/json',
      'user-agent': 'NEXUS/1.0 (spatial computing environment)',
    },
  });
  if (!response.ok) return null;
  return (await response.json()) as T;
}

let catalogue: CompetitionEntry[] | null = null;

export async function competitions(signal: AbortSignal): Promise<CompetitionEntry[]> {
  // The catalogue changes when StatsBomb publishes, which is a few times a
  // year -- holding it for the life of the process is generous enough.
  if (catalogue) return catalogue;
  catalogue = (await fetchJson<CompetitionEntry[]>('competitions.json', signal)) ?? [];
  return catalogue;
}

export interface MatchSummary {
  matchId: number;
  date: string;
  competition: string;
  season: string;
  stage?: string;
  home: string;
  away: string;
  score: string;
}

const normalise = (value: string) =>
  value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '');

/**
 * Find matches by team, competition or season. Any of them may be omitted;
 * with none, the most recent competitions are sampled so the model can see
 * what exists rather than guessing at identifiers.
 */
export async function findMatches(
  query: { team?: string; competition?: string; season?: string },
  signal: AbortSignal,
  limit = 12,
): Promise<MatchSummary[]> {
  const all = await competitions(signal);
  const wantedCompetition = query.competition ? normalise(query.competition) : null;
  const wantedSeason = query.season ? normalise(query.season) : null;
  const wantedTeam = query.team ? normalise(query.team) : null;

  const shortlist = all.filter((entry) => {
    if (wantedCompetition && !normalise(entry.competition_name).includes(wantedCompetition)) {
      return false;
    }
    if (wantedSeason && !normalise(entry.season_name).includes(wantedSeason)) return false;
    return true;
  });

  /*
   * Each competition-season is a separate file, so an unfiltered search would
   * be eighty downloads. Newest first, and stop as soon as there are enough.
   */
  const ordered = shortlist.sort((a, b) => b.season_name.localeCompare(a.season_name));
  const found: MatchSummary[] = [];

  for (const entry of ordered.slice(0, wantedTeam ? 14 : 3)) {
    const matches = await fetchJson<MatchEntry[]>(
      `matches/${entry.competition_id}/${entry.season_id}.json`,
      signal,
    );
    if (!matches) continue;

    for (const match of matches) {
      const home = match.home_team.home_team_name;
      const away = match.away_team.away_team_name;
      if (wantedTeam && !normalise(`${home} ${away}`).includes(wantedTeam)) continue;

      found.push({
        matchId: match.match_id,
        date: match.match_date,
        competition: match.competition.competition_name,
        season: match.season.season_name,
        stage: match.competition_stage?.name,
        home,
        away,
        score: `${match.home_score}-${match.away_score}`,
      });
      if (found.length >= limit) return found;
    }
  }

  return found;
}

export interface PlayerLine {
  player: string;
  team: string;
  shots: number;
  goals: number;
  xg: number;
  xa: number;
  passes: number;
  passAccuracy: number;
  keyPasses: number;
  progressivePasses: number;
  carries: number;
  progressiveCarries: number;
  duels: number;
  duelsWon: number;
}

/** The pitch is 120 long; a ball moved this much nearer goal has progressed. */
const PROGRESSIVE_METRES = 10;

function movesForward(from: number[] | undefined, to: number[] | undefined): boolean {
  if (!from || !to || from.length < 2 || to.length < 2) return false;
  // Distance to the opposition goal line, which is what "forward" means here.
  return to[0]! - from[0]! >= PROGRESSIVE_METRES;
}

/**
 * Every player's line from one match, computed from the events themselves.
 *
 * xA is credited the way StatsBomb models it: a shot names the pass that
 * created it, so the expected value of that shot belongs to whoever played
 * the pass. Summing assists instead would reward the finisher twice and the
 * passer only when the ball went in.
 */
export async function matchPlayerStats(
  matchId: number,
  signal: AbortSignal,
): Promise<{ match: MatchSummary | null; players: PlayerLine[] } | null> {
  const events = await fetchJson<EventEntry[]>(`events/${matchId}.json`, signal);
  if (!events) return null;

  const lines = new Map<string, PlayerLine>();
  const line = (event: EventEntry): PlayerLine | null => {
    const name = event.player?.name;
    if (!name) return null;
    let entry = lines.get(name);
    if (!entry) {
      entry = {
        player: name,
        team: event.team?.name ?? '',
        shots: 0,
        goals: 0,
        xg: 0,
        xa: 0,
        passes: 0,
        passAccuracy: 0,
        keyPasses: 0,
        progressivePasses: 0,
        carries: 0,
        progressiveCarries: 0,
        duels: 0,
        duelsWon: 0,
      };
      lines.set(name, entry);
    }
    return entry;
  };

  // Who played each pass, so a shot can hand its expected value back.
  const passer = new Map<string, string>();
  const completed = new Map<string, number>();

  for (const event of events) {
    const entry = line(event);
    if (!entry) continue;
    const kind = event.type.name;

    if (kind === 'Pass') {
      passer.set(event.id, entry.player);
      entry.passes += 1;
      if (!event.pass?.outcome) {
        completed.set(entry.player, (completed.get(entry.player) ?? 0) + 1);
      }
      if (event.pass?.shot_assist || event.pass?.goal_assist) entry.keyPasses += 1;
      if (movesForward(event.location, event.pass?.end_location)) entry.progressivePasses += 1;
    } else if (kind === 'Shot') {
      entry.shots += 1;
      entry.xg += event.shot?.statsbomb_xg ?? 0;
      if (event.shot?.outcome?.name === 'Goal') entry.goals += 1;
    } else if (kind === 'Carry') {
      entry.carries += 1;
      if (movesForward(event.location, event.carry?.end_location)) entry.progressiveCarries += 1;
    } else if (kind === 'Duel') {
      entry.duels += 1;
      const outcome = event.duel?.outcome?.name ?? '';
      if (outcome.includes('Won') || outcome === 'Success') entry.duelsWon += 1;
    }
  }

  // Second pass: hand each shot's expected value to whoever set it up.
  for (const event of events) {
    const keyPass = event.shot?.key_pass_id;
    if (!keyPass) continue;
    const name = passer.get(keyPass);
    if (!name) continue;
    const entry = lines.get(name);
    if (entry) entry.xa += event.shot?.statsbomb_xg ?? 0;
  }

  const players = [...lines.values()].map((entry) => ({
    ...entry,
    xg: Number(entry.xg.toFixed(2)),
    xa: Number(entry.xa.toFixed(2)),
    passAccuracy:
      entry.passes > 0
        ? Number((((completed.get(entry.player) ?? 0) / entry.passes) * 100).toFixed(1))
        : 0,
  }));

  players.sort((a, b) => b.xg + b.xa - (a.xg + a.xa));
  return { match: null, players };
}
