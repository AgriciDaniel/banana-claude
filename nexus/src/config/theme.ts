/**
 * NEXUS design tokens.
 *
 * Single source of truth for colour. Consumed by Tailwind (via CSS vars in
 * globals.css), by three.js materials, and by raw GLSL uniforms — so the HUD
 * and the volumetric scene are literally lit by the same numbers.
 */

export const PALETTE = {
  /** Deepest background. Not pure black — a cold, dense blue-black. */
  void: '#03060B',
  abyss: '#060B14',
  /** Structural surfaces (glass fills, panel grounds). */
  slate: '#0C1420',
  /** Primary holographic signal. Everything alive is this colour. */
  signal: '#63C9FF',
  /** Deep energy core, used for rim light and depth falloff. */
  core: '#2B6CFF',
  /** Cool white — text, highlights, specular. */
  lumen: '#E8F3FF',
  /** Muted text / inactive states. */
  ghost: '#5C7183',
  /** The only warm colour in the system. Warnings and hard limits only. */
  ember: '#FF7A2F',
  /** Success / lock-on confirmation. Barely-green cyan, stays in family. */
  lock: '#4FE0C4',
} as const;

export type PaletteKey = keyof typeof PALETTE;

/** Hex -> normalised [r,g,b] for GLSL uniforms and three.js Color. */
export function rgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

export const RGB = {
  void: rgb(PALETTE.void),
  signal: rgb(PALETTE.signal),
  core: rgb(PALETTE.core),
  lumen: rgb(PALETTE.lumen),
  ember: rgb(PALETTE.ember),
  lock: rgb(PALETTE.lock),
} as const;

/** Scene-wide spatial constants (metres). The room has no walls, only depth. */
export const SPACE = {
  /** Radius of the module carousel around the viewer. */
  orbitRadius: 4.2,
  /** Vertical centre of the ring relative to origin. */
  orbitHeight: 0.1,
  /** Card dimensions. */
  cardWidth: 1.34,
  cardHeight: 1.86,
  cardDepth: 0.055,
  cardRadius: 0.11,
  /** How far a focused card advances toward the viewer. */
  focusAdvance: 0.46,
  /** How far an expanded card advances toward the viewer. */
  expandAdvance: 1.9,
  /** Default camera seat. */
  /**
   * Camera seat. Set so the focused card fills roughly 55% of a 16:9 viewport:
   * dominant enough to read at a glance, open enough that both neighbours and
   * the volume behind them stay in frame. Closer than this and the ring stops
   * reading as a ring.
   */
  cameraStart: [0, 0.4, 9.9] as [number, number, number],
  cameraFocus: [0, 0.25, 8.4] as [number, number, number],
  /** Atmospheric bounds — the fog volume the particles live inside. */
  fogNear: 6,
  fogFar: 34,
} as const;
