import type { ModuleDefinition, ModuleMetric } from '@/config/modules';
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
 * Feed -> card face.
 *
 * The three numbers painted on each card are now measurements, not fixtures.
 * This is the one place that decides which three, and it is deliberately
 * separate from both the provider and the painter: what a module is worth
 * showing at a glance is an editorial decision, and it changes far more often
 * than either the data shape or the rendering.
 *
 * `level` drives the segmented bar, so it is always normalised to 0..1 with a
 * meaning that suits the metric - a share of a total, a proportion of a
 * sensible ceiling, or a confidence.
 */

export interface FaceState {
  metrics: ModuleMetric[];
  /** Overrides the module's static status pip when the feed says otherwise. */
  status: ModuleDefinition['status'];
  /** Short provenance line, painted small on the card. */
  source: string;
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

const compact = (n: number): string => {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${Math.round(n / 1e3)}K`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
};

const signed = (n: number, digits = 2) => `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;

/**
 * Quantise volatile readings.
 *
 * The card face is a painted canvas texture, and it is repainted whenever any
 * displayed value changes. Frame rate and audio level change on every sample,
 * which meant the System and Music cards were re-rasterising a 640x888 canvas
 * and re-uploading a texture up to twenty times a second - enough on its own to
 * take the whole environment from 145 fps to 12.
 *
 * Rounding to a step the eye cannot resolve anyway makes the face stable, and
 * the expanded panel still shows the unrounded value.
 */
const step = (value: number, size: number) => Math.round(value / size) * size;

/** Fall back to the module's declared placeholders when there is no feed yet. */
function idle(mod: ModuleDefinition, source: string): FaceState {
  return { metrics: mod.metrics, status: mod.status, source };
}

export function deriveFace(mod: ModuleDefinition, feed: ModuleFeed<unknown> | undefined): FaceState {
  if (!feed || !feed.data) {
    const source =
      feed?.status === 'unconfigured'
        ? 'SETUP REQUIRED'
        : feed?.status === 'error'
          ? 'UNAVAILABLE'
          : feed?.status === 'loading'
            ? 'LOADING'
            : '';
    const state = idle(mod, source);
    if (feed?.status === 'unconfigured') return { ...state, status: 'standby' };
    if (feed?.status === 'error') return { ...state, status: 'attention' };
    return state;
  }

  // Deliberately excludes any age or timestamp: those tick, and a ticking
  // string in the cache key would repaint the card every second.
  const source = feed.status === 'stale' ? `${feed.source} · STALE` : feed.source;

  switch (mod.id) {
    case 'weather': {
      const d = feed.data as WeatherData;
      return {
        source,
        status: d.condition === 'storm' ? 'attention' : 'online',
        metrics: [
          { label: 'TEMP', value: `${Math.round(d.temperature)}°`, level: clamp01((d.temperature + 10) / 45) },
          { label: 'WIND', value: `${Math.round(d.wind)}KM`, level: clamp01(d.wind / 60) },
          { label: 'CLOUD', value: `${Math.round(d.cloudCover)}%`, level: d.cloudCover / 100 },
        ],
      };
    }

    case 'stocks': {
      const d = feed.data as StocksData;
      return {
        source,
        status: d.totalPnl >= 0 ? 'online' : 'attention',
        metrics: [
          { label: 'VALUE', value: compact(d.totalValue), level: clamp01(d.totalValue / 100_000) },
          { label: 'DAY', value: signed(d.dayChangePct), level: clamp01(0.5 + d.dayChangePct / 8) },
          { label: 'P/L', value: signed(d.totalPnlPct, 1), level: clamp01(0.5 + d.totalPnlPct / 100) },
        ],
      };
    }

    case 'news': {
      const d = feed.data as NewsData;
      const fresh = d.articles.filter((a) => Date.now() - a.published < 6 * 3600_000).length;
      return {
        source,
        status: 'online',
        metrics: [
          { label: 'STORIES', value: String(d.articles.length), level: clamp01(d.articles.length / 20) },
          { label: 'FRESH', value: String(fresh), level: clamp01(fresh / 12) },
          { label: 'DIGEST', value: d.digest ? 'READY' : 'OFF', level: d.digest ? 1 : 0 },
        ],
      };
    }

    case 'sports': {
      const d = feed.data as SportsData;
      const live = d.recent.filter((f) => f.status === 'live').length;
      const leader = d.standings[0];
      return {
        source,
        status: live > 0 ? 'attention' : 'online',
        metrics: [
          { label: 'LIVE', value: String(live).padStart(2, '0'), level: clamp01(live / 5) },
          { label: 'NEXT', value: String(d.upcoming.length).padStart(2, '0'), level: clamp01(d.upcoming.length / 10) },
          { label: 'LEADER', value: (leader?.team ?? '—').slice(0, 9).toUpperCase(), level: leader ? 1 : 0 },
        ],
      };
    }

    case 'projects': {
      const d = feed.data as ProjectsData;
      const active = d.projects.filter((p) => p.status === 'active').length;
      const stars = d.projects.reduce((sum, p) => sum + (p.repo?.stars ?? 0), 0);
      return {
        source,
        status: 'online',
        metrics: [
          { label: 'ACTIVE', value: String(active).padStart(2, '0'), level: clamp01(active / 6) },
          { label: 'TOTAL', value: String(d.projects.length).padStart(2, '0'), level: clamp01(d.projects.length / 10) },
          { label: 'STARS', value: compact(stars), level: clamp01(stars / 500) },
        ],
      };
    }

    case 'calendar': {
      const d = feed.data as CalendarData;
      const hours = Math.floor(d.freeMinutes / 60);
      return {
        source,
        status: d.conflicts > 0 ? 'attention' : 'online',
        metrics: [
          { label: 'TODAY', value: String(d.todayCount).padStart(2, '0'), level: clamp01(d.todayCount / 8) },
          { label: 'CONFLICT', value: String(d.conflicts).padStart(2, '0'), level: clamp01(d.conflicts / 3) },
          { label: 'FREE', value: `${hours}H${String(d.freeMinutes % 60).padStart(2, '0')}`, level: clamp01(d.freeMinutes / 480) },
        ],
      };
    }

    case 'instagram': {
      const d = feed.data as InstagramData;
      return {
        source,
        status: 'online',
        metrics: [
          { label: 'FOLLOWERS', value: compact(d.followers), level: clamp01(d.followers / 100_000) },
          { label: 'REACH', value: compact(d.reach), level: clamp01(d.reach / 50_000) },
          { label: 'ENGAGE', value: `${d.engagementRate.toFixed(1)}%`, level: clamp01(d.engagementRate / 10) },
        ],
      };
    }

    case 'system': {
      const d = feed.data as SystemData;
      return {
        source,
        status: step(d.fps, 5) >= 45 ? 'online' : 'attention',
        metrics: [
          { label: 'FPS', value: String(step(d.fps, 5)), level: clamp01(step(d.fps, 5) / 60) },
          { label: 'THREADS', value: String(d.cores).padStart(2, '0'), level: clamp01(d.cores / 24) },
          {
            label: 'BATTERY',
            value: d.battery ? `${step(d.battery.level * 100, 5)}%` : 'AC',
            level: d.battery ? step(d.battery.level, 0.05) : 1,
          },
        ],
      };
    }

    case 'music': {
      const d = feed.data as MusicData;
      const bass = step(d.spectrum.slice(0, 8).reduce((a, b) => a + b, 0) / 8, 0.1);
      const level = step(d.level, 0.1);
      return {
        source,
        status: d.playing ? 'online' : 'standby',
        metrics: [
          { label: 'OUTPUT', value: d.playing ? 'AMBIENT' : 'MUTED', level: d.playing ? 1 : 0 },
          { label: 'LEVEL', value: `${Math.round(level * 100)}%`, level },
          { label: 'LOW', value: `${Math.round(bass * 100)}%`, level: bass },
        ],
      };
    }

    default:
      return idle(mod, source);
  }
}
