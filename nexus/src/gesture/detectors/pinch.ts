import type { GestureEvent, HandFrame } from '../types';
import { Cooldown, makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Pinch — the primary "grab" verb.
 *
 * Schmitt trigger on normalised thumb/index distance. The two thresholds are
 * far apart on purpose: a single threshold chatters at the boundary and makes
 * cards flicker between grabbed and dropped, which reads as broken tracking
 * rather than as a physical grip.
 */
const ENTER = 0.66;
const EXIT = 0.42;
/** Pinch must persist this long before it counts — rejects tracking spikes. */
const CONFIRM_MS = 45;

export class PinchDetector implements Detector {
  readonly id = 'pinch';
  private engaged = false;
  private candidateSince = 0;
  private cooldown = new Cooldown(90);

  update({ hand, now }: DetectorContext): GestureEvent | null {
    const p = hand.pinch;

    if (!this.engaged) {
      if (p >= ENTER) {
        if (this.candidateSince === 0) this.candidateSince = now;
        if (now - this.candidateSince >= CONFIRM_MS && this.cooldown.ready(now)) {
          this.engaged = true;
          this.candidateSince = 0;
          this.cooldown.arm(now);
          return makeEvent('pinch_start', hand, p, now);
        }
      } else {
        this.candidateSince = 0;
      }
      return null;
    }

    if (p <= EXIT) {
      this.engaged = false;
      this.candidateSince = 0;
      this.cooldown.arm(now);
      // Magnitude carries release speed so the drop can inherit momentum.
      return makeEvent('pinch_end', hand, 1 - p, now, Math.hypot(hand.velocity.x, hand.velocity.y));
    }
    return null;
  }

  get held(): boolean {
    return this.engaged;
  }

  /**
   * Give up a pinch that ended because the hand left, not because it opened.
   * Returns the closing event when one is owed, so the interface can unwind a
   * drag it would otherwise hold open indefinitely.
   */
  abandon(hand: HandFrame, now: number): GestureEvent | null {
    if (!this.engaged) return null;
    this.engaged = false;
    this.candidateSince = 0;
    return makeEvent('pinch_end', hand, 1, now);
  }

  reset(): void {
    this.engaged = false;
    this.candidateSince = 0;
    this.cooldown.reset();
  }
}
