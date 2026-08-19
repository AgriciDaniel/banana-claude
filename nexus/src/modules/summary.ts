import type {
  CalendarData,
  InstagramData,
  ModuleFeed,
  MusicData,
  NewsData,
  ProjectsData,
  SportsData,
  StocksData,
  SystemData,
  WeatherData,
} from './types';

/**
 * Module state, in a sentence the model can read.
 *
 * The assistant already drives the interface; from Phase 3 it can also SEE it.
 * These summaries are injected into every turn, which is what lets "what's the
 * weather" and "how is my portfolio doing" be answered from the same live feed
 * the cards are showing, rather than sent out to a web search that would
 * return a different number than the one on screen.
 *
 * Deliberately terse: this is prompt budget spent on every single turn.
 */

const money = (n: number) => Math.round(n).toLocaleString('en-US');
const pct = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;

export function summariseFeed(id: string, feed: ModuleFeed<unknown> | undefined): string | null {
  if (!feed) return null;
  if (feed.status === 'unconfigured') {
    return `${id}: not connected${feed.setupHint ? ` (${feed.setupHint.slice(0, 90)})` : ''}`;
  }
  if (!feed.data) {
    return feed.status === 'error' ? `${id}: unavailable (${feed.error ?? 'error'})` : null;
  }

  switch (id) {
    case 'weather': {
      const d = feed.data as WeatherData;
      const today = d.daily[0];
      return `weather: ${d.place}, ${Math.round(d.temperature)}C, ${d.description.toLowerCase()}, wind ${Math.round(d.wind)}km/h, humidity ${d.humidity}%${today ? `, today ${Math.round(today.min)}-${Math.round(today.max)}C` : ''}`;
    }

    case 'stocks': {
      const d = feed.data as StocksData;
      const movers = d.holdings
        .slice()
        .sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct))
        .slice(0, 3)
        .map((h) => `${h.symbol} ${h.price.toFixed(2)} ${pct(h.changePct)}`)
        .join(', ');
      return `stocks: portfolio ${money(d.totalValue)} USD, day ${pct(d.dayChangePct)}, total P/L ${money(d.totalPnl)} (${pct(d.totalPnlPct)}), market ${d.marketOpen ? 'open' : 'closed'}; ${movers}`;
    }

    case 'news': {
      const d = feed.data as NewsData;
      const heads = d.articles.slice(0, 6).map((a) => `"${a.title}" (${a.source})`).join('; ');
      return `news: ${d.articles.length} stories. Top: ${heads}`;
    }

    case 'sports': {
      const d = feed.data as SportsData;
      const last = d.recent[0];
      const next = d.upcoming[0];
      const top = d.standings.slice(0, 3).map((r) => `${r.rank}. ${r.team} ${r.points}pts`).join(', ');
      return `sports: ${d.league}.${last ? ` Last: ${last.home} ${last.homeScore ?? '-'}-${last.awayScore ?? '-'} ${last.away}.` : ''}${next ? ` Next: ${next.home} v ${next.away} on ${next.date}.` : ''} Table: ${top}`;
    }

    case 'projects': {
      const d = feed.data as ProjectsData;
      return `projects: ${d.projects
        .map((p) => `${p.name} (${p.status}${p.repo ? `, ${p.repo.stars} stars, ${p.repo.language ?? 'n/a'}` : ''})`)
        .join('; ')}`;
    }

    case 'calendar': {
      const d = feed.data as CalendarData;
      const next = d.events[0];
      return `calendar: ${d.todayCount} events today, ${d.conflicts} conflicts, ${Math.floor(d.freeMinutes / 60)}h${d.freeMinutes % 60}m free${next ? `. Next: "${next.title}" at ${new Date(next.start).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}` : ''}`;
    }

    case 'instagram': {
      const d = feed.data as InstagramData;
      return `instagram: @${d.username}, ${d.followers} followers, reach ${d.reach}, engagement ${d.engagementRate.toFixed(1)}%`;
    }

    case 'system': {
      const d = feed.data as SystemData;
      return `system: ${d.fps} fps, ${d.drawCalls} draw calls, ${d.cores} threads, GPU ${d.gpu}${d.battery ? `, battery ${Math.round(d.battery.level * 100)}%${d.battery.charging ? ' charging' : ''}` : ''}${d.network ? `, network ${d.network.type}` : ''}`;
    }

    case 'music': {
      const d = feed.data as MusicData;
      return `music: ${d.playing ? 'ambient bed playing' : 'muted'}, level ${Math.round(d.level * 100)}%. This module is a live spectrum analyser of the environment's own audio, not a track player.`;
    }

    default:
      return null;
  }
}
