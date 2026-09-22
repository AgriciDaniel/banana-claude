/**
 * Module registry.
 *
 * Each entry is a future surface of the OS. Phase 1 renders them as
 * holographic cards; later phases mount real feature modules against the same
 * ids. Adding a module here is the ONLY change needed to put it in the ring.
 */

export type ModuleCategory = 'social' | 'finance' | 'work' | 'life' | 'system' | 'media';

export interface ModuleMetric {
  label: string;
  value: string;
  /** 0..1 — drives the readout bar on the card face. */
  level: number;
}

export interface ModuleDefinition {
  id: string;
  /** Display name on the card face and in the HUD. */
  name: string;
  /** Three-character system code, Teenage-Engineering style. */
  code: string;
  category: ModuleCategory;
  /** One-line descriptor shown when the card is focused. */
  descriptor: string;
  /** Faux telemetry painted into the card texture. */
  metrics: ModuleMetric[];
  /** Deterministic seed for the sparkline + idle drift phase. */
  seed: number;
  /** Modules not yet wired to data render a dimmer "standby" plate. */
  status: 'online' | 'standby' | 'attention';
}

export const MODULES: ModuleDefinition[] = [
  {
    id: 'instagram',
    name: 'Instagram',
    code: 'IGM',
    category: 'social',
    descriptor: 'Social graph ingest / reach telemetry',
    // Placeholders, not figures: the card must never look like it is reading
    // an account it has not reached yet. Real values land the moment the feed
    // does; see deriveFace.
    metrics: [
      { label: 'REACH', value: '--', level: 0.3 },
      { label: 'ENGAGE', value: '--', level: 0.25 },
      { label: 'QUEUE', value: '--', level: 0.2 },
    ],
    seed: 0.11,
    status: 'standby',
  },
  {
    id: 'youtube',
    name: 'YouTube',
    code: 'YTB',
    category: 'social',
    descriptor: 'Channel telemetry / audience reach',
    metrics: [
      { label: 'SUBS', value: '--', level: 0.3 },
      { label: 'AVG VIEWS', value: '--', level: 0.25 },
      { label: 'SHORTS', value: '--', level: 0.2 },
    ],
    seed: 0.37,
    status: 'standby',
  },
  {
    id: 'stocks',
    name: 'Stocks',
    code: 'MKT',
    category: 'finance',
    descriptor: 'Market surface / position exposure',
    metrics: [
      { label: 'INDEX', value: '+1.24%', level: 0.62 },
      { label: 'VOL', value: '14.8', level: 0.55 },
      { label: 'RISK', value: 'MOD', level: 0.48 },
    ],
    seed: 0.27,
    status: 'standby',
  },
  {
    id: 'projects',
    name: 'Projects',
    code: 'PRJ',
    category: 'work',
    descriptor: 'Active workstreams / build pipeline',
    metrics: [
      { label: 'ACTIVE', value: '07', level: 0.7 },
      { label: 'BLOCKED', value: '01', level: 0.18 },
      { label: 'VELOCITY', value: '0.86', level: 0.86 },
    ],
    seed: 0.39,
    status: 'standby',
  },
  {
    id: 'sports',
    name: 'Sports',
    code: 'ATH',
    category: 'life',
    descriptor: 'Fixture feed / performance tracking',
    metrics: [
      { label: 'LIVE', value: '02', level: 0.35 },
      { label: 'LOAD', value: '61%', level: 0.61 },
      { label: 'RECOV', value: 'GOOD', level: 0.78 },
    ],
    seed: 0.53,
    status: 'standby',
  },
  {
    id: 'calendar',
    name: 'Calendar',
    code: 'CAL',
    category: 'work',
    descriptor: 'Temporal scheduling / conflict resolution',
    metrics: [
      { label: 'TODAY', value: '04', level: 0.44 },
      { label: 'CONFLICT', value: '01', level: 0.2 },
      { label: 'FREE', value: '3H20', level: 0.66 },
    ],
    seed: 0.62,
    status: 'attention',
  },
  {
    id: 'weather',
    name: 'Weather',
    code: 'ATM',
    category: 'life',
    descriptor: 'Atmospheric model / local conditions',
    metrics: [
      { label: 'TEMP', value: '18°', level: 0.5 },
      { label: 'WIND', value: '12KM', level: 0.32 },
      { label: 'PRESS', value: '1014', level: 0.58 },
    ],
    seed: 0.74,
    status: 'standby',
  },
  {
    id: 'ai',
    name: 'AI',
    code: 'CTX',
    category: 'system',
    descriptor: 'Reasoning core / reserved for phase two',
    metrics: [
      { label: 'CTX', value: '——', level: 0.0 },
      { label: 'MODEL', value: 'OFFLINE', level: 0.0 },
      { label: 'TOKENS', value: '0', level: 0.0 },
    ],
    seed: 0.85,
    status: 'standby',
  },
  {
    id: 'news',
    name: 'News',
    code: 'WIR',
    category: 'media',
    descriptor: 'Wire aggregation / signal filtering',
    metrics: [
      { label: 'FEEDS', value: '12', level: 0.6 },
      { label: 'UNREAD', value: '38', level: 0.76 },
      { label: 'NOISE', value: 'LOW', level: 0.22 },
    ],
    seed: 0.93,
    status: 'standby',
  },
  {
    id: 'music',
    name: 'Music',
    code: 'SND',
    category: 'media',
    descriptor: 'Playback surface / spectral analysis',
    metrics: [
      { label: 'TRACK', value: '——', level: 0.0 },
      { label: 'BPM', value: '——', level: 0.0 },
      { label: 'OUT', value: 'AMBIENT', level: 0.3 },
    ],
    seed: 0.06,
    status: 'standby',
  },
  {
    id: 'system',
    name: 'System',
    code: 'SYS',
    category: 'system',
    descriptor: 'Runtime diagnostics / render pipeline',
    metrics: [
      { label: 'RENDER', value: 'WEBGL2', level: 0.9 },
      { label: 'THREADS', value: '04', level: 0.5 },
      { label: 'THERMAL', value: 'NOMINAL', level: 0.35 },
    ],
    seed: 0.18,
    status: 'online',
  },
];

export const MODULE_COUNT = MODULES.length;

export function moduleAt(index: number): ModuleDefinition {
  const wrapped = ((index % MODULE_COUNT) + MODULE_COUNT) % MODULE_COUNT;
  return MODULES[wrapped]!;
}

export function moduleById(id: string): ModuleDefinition | undefined {
  return MODULES.find((m) => m.id === id);
}
