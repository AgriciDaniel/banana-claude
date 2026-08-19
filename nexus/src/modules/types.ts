/**
 * Module data contracts.
 *
 * Phase 3 makes every module real. The rule this file enforces is honesty:
 * every feed carries where its data came from and whether it is actually live,
 * so the interface can never imply a number is current when it is not.
 *
 * `unconfigured` is a first-class state, not an error. Instagram and Calendar
 * need credentials this build cannot invent; saying so plainly is the correct
 * behaviour, and it is visually distinct from a failure.
 */

export type ModuleStatus =
  | 'idle'
  | 'loading'
  | 'live'
  | 'stale'
  | 'error'
  /** Needs credentials or configuration that are not present. */
  | 'unconfigured';

export interface ModuleFeed<T> {
  status: ModuleStatus;
  data: T | null;
  error: string | null;
  /** epoch ms of the successful fetch backing `data`. */
  fetchedAt: number;
  /** Human-readable provenance, surfaced in the UI. */
  source: string;
  /** Set when the module needs setup; rendered as instructions. */
  setupHint?: string;
}

export const emptyFeed = <T>(): ModuleFeed<T> => ({
  status: 'idle',
  data: null,
  error: null,
  fetchedAt: 0,
  source: '',
});

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------

/** Coarse condition, used to drive the actual weather in the 3D environment. */
export type SkyCondition = 'clear' | 'cloud' | 'fog' | 'rain' | 'snow' | 'storm';

export interface WeatherData {
  place: string;
  temperature: number;
  feelsLike: number;
  humidity: number;
  wind: number;
  pressure: number;
  cloudCover: number;
  precipitation: number;
  isDay: boolean;
  condition: SkyCondition;
  description: string;
  /** Next 24 hours, one entry per hour. */
  hourly: { t: string; temp: number; precip: number }[];
  daily: { day: string; min: number; max: number; condition: SkyCondition }[];
}

// ---------------------------------------------------------------------------
// Stocks
// ---------------------------------------------------------------------------

export interface Holding {
  symbol: string;
  name: string;
  price: number;
  previousClose: number;
  changePct: number;
  currency: string;
  sector: string;
  /** Units held, from the local portfolio config. */
  units: number;
  value: number;
  costBasis: number;
  pnl: number;
  pnlPct: number;
  /** Closing prices, oldest first. */
  history: number[];
}

export interface StocksData {
  holdings: Holding[];
  totalValue: number;
  totalCost: number;
  totalPnl: number;
  totalPnlPct: number;
  dayChangePct: number;
  /** Sector -> share of portfolio value, 0..1. */
  allocation: { label: string; weight: number; value: number }[];
  marketOpen: boolean;
}

// ---------------------------------------------------------------------------
// News
// ---------------------------------------------------------------------------

export interface Article {
  id: string;
  title: string;
  summary: string;
  source: string;
  link: string;
  published: number;
}

export interface NewsData {
  articles: Article[];
  /** Model-written digest of the whole batch. Absent without an API key. */
  digest: string | null;
}

// ---------------------------------------------------------------------------
// Sports
// ---------------------------------------------------------------------------

export interface Fixture {
  id: string;
  home: string;
  away: string;
  homeScore: number | null;
  awayScore: number | null;
  date: string;
  status: 'finished' | 'upcoming' | 'live';
  league: string;
}

export interface StandingRow {
  rank: number;
  team: string;
  played: number;
  points: number;
  goalDiff: number;
  form?: string;
}

export interface SportsData {
  league: string;
  recent: Fixture[];
  upcoming: Fixture[];
  standings: StandingRow[];
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface ProjectAsset {
  kind: 'image' | 'video';
  url: string;
  caption?: string;
}

export interface ProjectPrompt {
  at: string;
  text: string;
  model?: string;
}

export interface Project {
  id: string;
  name: string;
  tagline: string;
  description: string;
  status: 'active' | 'shipped' | 'paused';
  tags: string[];
  assets: ProjectAsset[];
  prompts: ProjectPrompt[];
  repo?: {
    url: string;
    stars: number;
    forks: number;
    language: string | null;
    pushedAt: string | null;
    openIssues: number;
  };
}

export interface ProjectsData {
  projects: Project[];
}

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export interface CalendarEvent {
  id: string;
  title: string;
  start: number;
  end: number;
  allDay: boolean;
  location?: string;
}

export interface CalendarData {
  events: CalendarEvent[];
  todayCount: number;
  /** Overlapping pairs — the card's "conflict" readout is real. */
  conflicts: number;
  /** Minutes of unbooked time left in the working day. */
  freeMinutes: number;
}

// ---------------------------------------------------------------------------
// Instagram
// ---------------------------------------------------------------------------

export interface InstagramPost {
  id: string;
  caption: string;
  mediaType: string;
  url: string;
  permalink: string;
  likes: number;
  comments: number;
  reach: number;
  timestamp: number;
}

export interface InstagramData {
  username: string;
  followers: number;
  follows: number;
  posts: number;
  reach: number;
  /**
   * Replaces the old `impressions`, deprecated across all API versions on
   * 21 April 2025. Counts plays and displays across reels, posts and stories.
   */
  views: number;
  /**
   * Replaces `profile_views`, which no longer exists on the insights edge.
   * Accounts that interacted with the profile in the period.
   */
  accountsEngaged: number;
  /** Follower delta per day over the reported window. */
  growth: { day: string; value: number }[];
  engagementRate: number;
  reels: number;
  top: InstagramPost[];
}

// ---------------------------------------------------------------------------
// Client-side modules
// ---------------------------------------------------------------------------

export interface SystemData {
  cores: number;
  memoryGb: number;
  /** Chrome-only JS heap, in MB. Null elsewhere. */
  heapUsedMb: number | null;
  heapLimitMb: number | null;
  battery: { level: number; charging: boolean } | null;
  network: { type: string; downlink: number; rtt: number } | null;
  storage: { usedMb: number; quotaMb: number } | null;
  gpu: string;
  renderer: string;
  fps: number;
  frameMs: number;
  drawCalls: number;
  triangles: number;
  platform: string;
  uptimeSec: number;
}

export interface MusicData {
  /** 32-band spectrum of everything the environment is producing, 0..1. */
  spectrum: number[];
  level: number;
  /** What is currently generating sound. */
  sources: string[];
  playing: boolean;
}
