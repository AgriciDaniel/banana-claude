import { PALETTE } from './theme';

/**
 * The six worlds.
 *
 * An environment is a set of numbers, not a scene. Everything the renderer
 * already draws - fog, grid, beams, motes, lights, horizon - reads its
 * parameters from the active environment, and switching worlds interpolates
 * every one of those numbers at once. Nothing is created or destroyed, which
 * is why a morph costs no allocations and never drops a frame.
 *
 * Adding a seventh world means adding an entry here and nothing else.
 */

export type EnvironmentId =
  | 'studio'
  | 'lab'
  | 'observatory'
  | 'command'
  | 'ocean'
  | 'fog';

export interface Environment {
  id: EnvironmentId;
  /** Untranslated fallback; the switcher uses the catalogue. */
  name: string;

  // --- atmosphere ---------------------------------------------------------
  deep: string;
  mid: string;
  glow: string;
  /** Multiplier on the fbm fog in the backdrop shader. */
  density: number;
  /** Scene fog density. The single strongest lever on mood. */
  fog: number;
  /** Height of the horizon glow band, 0..1. */
  horizon: number;

  // --- ground -------------------------------------------------------------
  grid: string;
  gridSpacing: number;
  gridStrength: number;
  floorY: number;

  // --- volumetrics --------------------------------------------------------
  beamScale: number;
  beamIntensity: number;
  beamColor: string;

  // --- motes --------------------------------------------------------------
  moteCore: string;
  moteEdge: string;
  moteDrift: number;
  moteSize: number;
  moteOpacity: number;

  // --- lighting -----------------------------------------------------------
  ambient: number;
  keyIntensity: number;
  keyColor: string;
  fillIntensity: number;
  fillColor: string;
  /** Reflection strength on the card glass. */
  envIntensity: number;
}

export const ENVIRONMENTS: Record<EnvironmentId, Environment> = {
  /** Cold, clean, almost empty. The room as a photographic sweep. */
  studio: {
    id: 'studio',
    name: 'Minimal Studio',
    deep: '#0B1017',
    mid: '#151D28',
    glow: '#9FC4E8',
    density: 0.35,
    fog: 0.016,
    horizon: 0.75,
    grid: '#8FB6D8',
    gridSpacing: 1.4,
    gridStrength: 0.35,
    floorY: -3.1,
    beamScale: 0.35,
    beamIntensity: 0.35,
    beamColor: '#E8F3FF',
    moteCore: '#FFFFFF',
    moteEdge: '#A9C8E4',
    moteDrift: 0.6,
    moteSize: 1.7,
    moteOpacity: 0.5,
    ambient: 0.55,
    keyIntensity: 140,
    keyColor: '#FFFFFF',
    fillIntensity: 22,
    fillColor: '#8FB6D8',
    envIntensity: 1.8,
  },

  /** The Phase 1 default. Dark, blue, volumetric. */
  lab: {
    id: 'lab',
    name: 'Dark Lab',
    deep: PALETTE.void,
    mid: PALETTE.abyss,
    glow: PALETTE.core,
    density: 0.85,
    fog: 0.042,
    horizon: 1,
    grid: PALETTE.signal,
    gridSpacing: 0.85,
    gridStrength: 1,
    floorY: -3.1,
    beamScale: 1,
    beamIntensity: 1,
    beamColor: PALETTE.signal,
    moteCore: PALETTE.lumen,
    moteEdge: PALETTE.core,
    moteDrift: 1.35,
    moteSize: 2.4,
    moteOpacity: 0.85,
    ambient: 0.18,
    keyIntensity: 90,
    keyColor: PALETTE.lumen,
    fillIntensity: 38,
    fillColor: PALETTE.core,
    envIntensity: 1.1,
  },

  /** High, clear and cathedral-like. Long shafts, thin air. */
  observatory: {
    id: 'observatory',
    name: 'Glass Observatory',
    deep: '#04080F',
    mid: '#0A1524',
    glow: '#7FD4FF',
    density: 0.45,
    fog: 0.02,
    horizon: 1.35,
    grid: '#63C9FF',
    gridSpacing: 1.9,
    gridStrength: 0.55,
    floorY: -3.6,
    beamScale: 1.7,
    beamIntensity: 1.5,
    beamColor: '#BFE9FF',
    moteCore: '#FFFFFF',
    moteEdge: '#5FA8E0',
    moteDrift: 0.85,
    moteSize: 2.1,
    moteOpacity: 0.7,
    ambient: 0.26,
    keyIntensity: 130,
    keyColor: '#DCF1FF',
    fillIntensity: 30,
    fillColor: '#2B6CFF',
    envIntensity: 2.1,
  },

  /** Warm, dense, instrumented. The only world where amber is structural. */
  command: {
    id: 'command',
    name: 'Industrial Command',
    deep: '#0A0705',
    mid: '#17100A',
    glow: '#FF9A4D',
    density: 1.1,
    fog: 0.05,
    horizon: 0.85,
    grid: '#FF8A3C',
    gridSpacing: 0.55,
    gridStrength: 1.25,
    floorY: -2.9,
    beamScale: 1.25,
    beamIntensity: 1.2,
    beamColor: '#FFB070',
    moteCore: '#FFD9B0',
    moteEdge: '#C2521A',
    moteDrift: 1.7,
    moteSize: 2.2,
    moteOpacity: 0.9,
    ambient: 0.2,
    keyIntensity: 70,
    keyColor: '#FFC79A',
    fillIntensity: 46,
    fillColor: '#8A3B10',
    envIntensity: 0.9,
  },

  /** Wide, low and slow. A horizon you cannot reach. */
  ocean: {
    id: 'ocean',
    name: 'Ocean Platform',
    deep: '#01090E',
    mid: '#04212B',
    glow: '#2FD8C4',
    density: 0.95,
    fog: 0.034,
    horizon: 1.6,
    grid: '#3FE0C8',
    gridSpacing: 1.15,
    gridStrength: 0.8,
    floorY: -2.4,
    beamScale: 0.8,
    beamIntensity: 0.75,
    beamColor: '#6FF2DC',
    moteCore: '#DFFFF8',
    moteEdge: '#128C7C',
    moteDrift: 2.1,
    moteSize: 2.6,
    moteOpacity: 0.75,
    ambient: 0.22,
    keyIntensity: 80,
    keyColor: '#CFFFF6',
    fillIntensity: 40,
    fillColor: '#0E6E63',
    envIntensity: 1.3,
  },

  /** Almost nothing is visible. Everything is felt at one metre. */
  fog: {
    id: 'fog',
    name: 'Fog Chamber',
    deep: '#080A0D',
    mid: '#141920',
    glow: '#93A6B8',
    density: 1.6,
    fog: 0.085,
    horizon: 0.5,
    grid: '#7E93A6',
    gridSpacing: 1.05,
    gridStrength: 0.25,
    floorY: -3.0,
    beamScale: 1.45,
    beamIntensity: 1.9,
    beamColor: '#C6D6E4',
    moteCore: '#FFFFFF',
    moteEdge: '#6B7E90',
    moteDrift: 0.5,
    moteSize: 3.1,
    moteOpacity: 0.55,
    ambient: 0.34,
    keyIntensity: 55,
    keyColor: '#D5E2EE',
    fillIntensity: 26,
    fillColor: '#46586B',
    envIntensity: 0.7,
  },
};

export const ENVIRONMENT_ORDER: EnvironmentId[] = [
  'lab',
  'studio',
  'observatory',
  'command',
  'ocean',
  'fog',
];

/**
 * Modules that pull the world with them.
 *
 * Expanding one of these morphs the environment to match, and collapsing it
 * returns to whatever the user had chosen. The mapping is data, so binding a
 * future module to a world is a one-line change.
 */
export const MODULE_WORLDS: Partial<Record<string, EnvironmentId>> = {
  projects: 'studio',
  stocks: 'command',
  weather: 'ocean',
  news: 'observatory',
  system: 'lab',
  music: 'fog',
};
