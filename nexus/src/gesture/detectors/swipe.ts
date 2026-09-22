import type { GestureEvent } from '../types';
import { Cooldown, SampleRing, makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Horizontal swipe — rotates the ring.
 *
 * A swipe is a *ballistic* motion, so it is validated on three axes at once:
 * speed, net travel inside a short window, and straightness. Requiring all
 * three kills the two classic false positives — slow hand repositioning, and
 * the return stroke after a real swipe.
 */
const WINDOW_MS = 260;
const MIN_TRAVEL = 0.15; // normalised video width
const MIN_SPEED = 0.85; // normalised units / second
const MAX_VERTICAL_RATIO = 0.62; // |dy| / |dx|
const COOLDOWN_MS = 420;

export class SwipeDetector implements Detector {
  readonly id = 'swipe';
  private ring = new SampleRing(24);
  private cooldown = new Cooldown(COOLDOWN_MS);

  update({ hand, now, grabbing }: DetectorContext): GestureEvent | null {
    this.ring.push(hand.palm.x, hand.palm.y, now);

    // A pinched or grabbing hand is manipulating, not navigating.
    if (grabbing || hand.pinch > 0.5) return null;
    // Swiping is done with an open-ish hand; a fist travelling fast is a throw.
    if (hand.openness < 0.4) return null;
    if (!this.cooldown.ready(now)) return null;
    if (this.ring.size < 5) return null;

    const start = this.ring.oldestWithin(now, WINDOW_MS);
    const end = this.ring.newest();
    if (!start || !end) return null;

    const dtSec = (end.t - start.t) / 1000;
    if (dtSec < 0.04) return null;

    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const travel = Math.abs(dx);
    if (travel < MIN_TRAVEL) return null;
    if (Math.abs(dy) / travel > MAX_VERTICAL_RATIO) return null;

    const speed = travel / dtSec;
    if (speed < MIN_SPEED) return null;

    this.cooldown.arm(now);
    this.ring.clear();

    // Coordinates are pre-mirrored, so +x is the user's right.
    const kind = dx > 0 ? 'swipe_right' : 'swipe_left';
    const confidence = Math.min(1, (speed / MIN_SPEED) * 0.45 + (travel / MIN_TRAVEL) * 0.35);
    return makeEvent(kind, hand, confidence, now, speed);
  }

  reset(): void {
    this.ring.clear();
    this.cooldown.reset();
  }
}
