import type { GestureEvent } from '../types';
import { makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Palm held still — the system freeze.
 *
 * Deliberately the slowest gesture in the set. Freezing the world is a modal
 * action, so it demands a held, unambiguous posture: flat open hand, no pinch,
 * near-zero palm motion, sustained. Release is instant and forgiving — you
 * should never have to fight to un-freeze.
 */
const HOLD_MS = 620;
const MAX_SPEED = 0.09; // normalised units / second
const MIN_OPENNESS = 0.68;
const RELEASE_OPENNESS = 0.45;
const RELEASE_SPEED = 0.34;

export class PalmHoldDetector implements Detector {
  readonly id = 'palmHold';
  private since = 0;
  private latched = false;

  update({ hand, now }: DetectorContext): GestureEvent | null {
    const speed = Math.hypot(hand.velocity.x, hand.velocity.y);

    if (this.latched) {
      const broken = hand.openness < RELEASE_OPENNESS || speed > RELEASE_SPEED || hand.pinch > 0.5;
      if (broken) {
        this.latched = false;
        this.since = 0;
        return makeEvent('palm_release', hand, 1, now);
      }
      return null;
    }

    const steady = hand.openness >= MIN_OPENNESS && speed <= MAX_SPEED && hand.pinch < 0.25;
    if (!steady) {
      this.since = 0;
      return null;
    }

    if (this.since === 0) this.since = now;
    const held = now - this.since;
    if (held >= HOLD_MS) {
      this.latched = true;
      this.since = 0;
      return makeEvent('palm_hold', hand, 1, now, held);
    }
    return null;
  }

  /** 0..1 progress toward the freeze — the HUD draws this as a filling ring. */
  progress(now: number): number {
    if (this.latched) return 1;
    if (this.since === 0) return 0;
    return Math.min(1, (now - this.since) / HOLD_MS);
  }

  get frozen(): boolean {
    return this.latched;
  }

  reset(): void {
    this.since = 0;
    this.latched = false;
  }
}
