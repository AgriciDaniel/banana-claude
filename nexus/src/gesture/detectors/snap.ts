import type { GestureEvent } from '../types';
import { Cooldown, makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Finger snap.
 *
 * Thresholds here are not guesses. They were read off a recording of a real
 * hand snapping four times in front of the camera, and every number below sits
 * in the middle of a gap the data actually left open.
 *
 * A snap has two halves and the detector needs both, because either one alone
 * is something else entirely:
 *
 *   charge  thumb pad against the middle pad, middle finger extended out to
 *           meet it. Thumb-middle gap fell to ~0.18 spans, middle-to-wrist
 *           reach rose to ~1.4 spans.
 *   strike  the middle finger flies off the thumb and slaps the base of the
 *           palm. Reach collapses to ~0.65 spans and the gap opens to ~0.72,
 *           inside a single 83ms camera frame.
 *
 * Requiring the reach to COLLAPSE is what separates a snap from a hand simply
 * opening: the recording caught the hand flying open at 10.4 spans/second,
 * faster than either real snap, but travelling the other way.
 *
 * Reach is measured from the wrist, so the whole test is unaffected by the
 * hand moving across the frame.
 */

/** Thumb-middle gap while charged, in spans. Measured: 0.10-0.33. */
const CHARGE_GAP = 0.34;
/** Middle-finger reach while charged. Measured: 1.24-1.6. */
const CHARGE_REACH = 1.15;
/** Reach after the strike. Measured: 0.58-0.80. */
const STRIKE_REACH = 0.85;
/** Thumb-middle gap after the strike. Measured: 0.57-0.77. */
const RELEASE_GAP = 0.55;
/** Collapse rate in spans per second. Measured: 5.3-9.5 for real snaps. */
const MIN_RATE = 5;
/**
 * How stale the charge may be when the strike lands. At 12Hz the charged
 * frame is the one immediately before, ~80ms back; this leaves room for a
 * dropped frame without accepting a charge from a second ago.
 */
const CHARGE_WINDOW_MS = 250;
const COOLDOWN_MS = 600;

export class SnapDetector implements Detector {
  readonly id = 'snap';
  private chargedAt = -1;
  private prevReach = -1;
  private cooldown = new Cooldown(COOLDOWN_MS);

  update({ hand, dt, now }: DetectorContext): GestureEvent | null {
    const gap = hand.snapGap;
    const reach = hand.middleReach;
    const previous = this.prevReach;
    this.prevReach = reach;

    if (gap <= CHARGE_GAP && reach >= CHARGE_REACH) this.chargedAt = now;
    if (previous < 0 || this.chargedAt < 0) return null;

    // Positive while the finger is folding back toward the wrist.
    const rate = (previous - reach) / Math.max(dt, 1e-4);

    const struck = reach <= STRIKE_REACH && gap >= RELEASE_GAP && rate >= MIN_RATE;
    if (!struck) return null;
    if (now - this.chargedAt > CHARGE_WINDOW_MS) return null;
    if (!this.cooldown.ready(now)) return null;

    this.cooldown.arm(now);
    this.chargedAt = -1;
    const confidence = Math.min(1, rate / (MIN_RATE * 1.8));
    return makeEvent('snap', hand, confidence, now, rate);
  }

  reset(): void {
    this.chargedAt = -1;
    this.prevReach = -1;
  }
}
