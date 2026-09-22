import { SPACE } from '@/config/theme';
import { MODULE_COUNT } from '@/config/modules';
import { noise1, TAU } from '@/core/math';
import type { CardState } from '@/core/types';

/**
 * Pure geometry for the ring. No three.js, no React — which means the layout
 * can be unit-tested, reasoned about, and reused by the physics attractor
 * without instantiating a scene.
 */

export const SLOT_STEP = TAU / MODULE_COUNT;

/** World angle of slot `index` given the ring's current rotation. */
export function slotAngle(index: number, ringAngle: number): number {
  return ringAngle + index * SLOT_STEP;
}

/**
 * Slot centre in world space. The ring is a circle on the XZ plane.
 *
 * `radius` is a parameter rather than a constant so the two-handed spread dial
 * can open and close the ring physically. Callers pass
 * `SPACE.orbitRadius * interaction.spread`; the default keeps this pure for
 * anything that just wants the resting layout.
 */
export function slotPosition(
  angle: number,
  out: [number, number, number],
  radius: number = SPACE.orbitRadius,
): void {
  out[0] = Math.sin(angle) * radius;
  out[1] = SPACE.orbitHeight;
  out[2] = Math.cos(angle) * radius;
}

/** Current ring radius, including the two-handed spread. */
export function liveRadius(spread: number): number {
  return SPACE.orbitRadius * spread;
}

/** Outward normal of a slot — the direction a card at that slot faces. */
export function slotNormal(angle: number, out: [number, number, number]): void {
  out[0] = Math.sin(angle);
  out[1] = 0;
  out[2] = Math.cos(angle);
}

/**
 * How "front and centre" a slot is, 0..1.
 * Drives depth-of-field focus, card opacity, and which card the ring snaps to.
 */
export function frontness(angle: number): number {
  return (Math.cos(angle) + 1) * 0.5;
}

/** Slot index closest to the viewer for a given ring angle. */
export function frontIndex(ringAngle: number): number {
  const raw = Math.round(-ringAngle / SLOT_STEP);
  return ((raw % MODULE_COUNT) + MODULE_COUNT) % MODULE_COUNT;
}

/** Ring angle that puts `index` dead centre. */
export function angleForIndex(index: number): number {
  return -index * SLOT_STEP;
}

/** Per-state target for how far a card advances along its own normal. */
export function stateAdvance(state: CardState): number {
  switch (state) {
    case 'hovered':
      return 0.14;
    case 'focused':
      return SPACE.focusAdvance;
    case 'selected':
      return SPACE.focusAdvance + 0.26;
    default:
      return 0;
  }
}

/** Per-state uniform scale. */
export function stateScale(state: CardState): number {
  switch (state) {
    case 'hovered':
      return 1.035;
    case 'focused':
      return 1.09;
    case 'selected':
      return 1.16;
    case 'dragging':
      return 1.2;
    case 'expanded':
      return 1.62;
    default:
      return 1;
  }
}

/** Per-state frame energy, 0..1. This is what the border shader consumes. */
export function stateEnergy(state: CardState): number {
  switch (state) {
    case 'hovered':
      return 0.38;
    case 'focused':
      return 0.56;
    case 'selected':
      return 0.86;
    case 'dragging':
      return 1;
    case 'expanded':
      return 0.95;
    default:
      return 0.13;
  }
}

/** Vertical lift, so raised states also read from the side. */
export function stateLift(state: CardState): number {
  switch (state) {
    case 'hovered':
      return 0.05;
    case 'focused':
      return 0.1;
    case 'selected':
      return 0.16;
    case 'dragging':
      return 0.22;
    default:
      return 0;
  }
}

/**
 * Idle drift.
 *
 * Each card gets its own incommensurate periods seeded from its index, so the
 * ring never visibly breathes in unison — that synchronisation is the single
 * most common tell that a "floating" UI is on a timer.
 */
export function idleDrift(
  seed: number,
  time: number,
  out: [number, number, number, number, number],
): void {
  const t = time * 0.24;
  out[0] = noise1(t * 0.83 + seed * 11.3, seed) * 0.045;
  out[1] = noise1(t * 0.61 + seed * 27.1, seed + 3) * 0.075 + Math.sin(t * 0.7 + seed * 6.28) * 0.022;
  out[2] = noise1(t * 0.47 + seed * 41.7, seed + 7) * 0.038;
  // Tilt, radians.
  out[3] = noise1(t * 0.55 + seed * 17.9, seed + 11) * 0.045;
  out[4] = noise1(t * 0.42 + seed * 31.5, seed + 13) * 0.055;
}
