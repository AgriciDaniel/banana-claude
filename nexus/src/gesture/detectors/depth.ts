import type { GestureEvent } from '../types';
import { Cooldown, makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Pull / push along the camera axis — expand and collapse.
 *
 * MediaPipe's per-landmark z is noisy and only weakly metric, so depth is
 * inferred from *apparent hand span* instead: the hand grows on the sensor as
 * it approaches. Span is compared against a slow-moving baseline so the
 * gesture works wherever the user happens to be sitting, and the baseline
 * freezes during a stroke so a slow pull cannot be absorbed by its own drift.
 */
const BASELINE_LAMBDA = 0.55; // baseline follow rate, per second
const TRIGGER_RATIO = 0.19; // fractional span change that counts
const MIN_RATE = 0.28; // per second — rejects slow reaching
const COOLDOWN_MS = 620;

export class DepthDetector implements Detector {
  readonly id = 'depth';
  private baseline = 0;
  private cooldown = new Cooldown(COOLDOWN_MS);
  private strokeLock = false;

  update({ hand, dt, now }: DetectorContext): GestureEvent | null {
    const span = hand.span;
    if (span <= 0) return null;

    if (this.baseline === 0) {
      this.baseline = span;
      return null;
    }

    const ratio = span / this.baseline - 1;
    const rate = hand.depthVelocity;

    // Freeze the baseline mid-stroke, otherwise it chases the gesture.
    const inStroke = Math.abs(ratio) > TRIGGER_RATIO * 0.45;
    this.strokeLock = inStroke;
    if (!this.strokeLock) {
      this.baseline += (span - this.baseline) * (1 - Math.exp(-BASELINE_LAMBDA * dt));
    }

    if (!this.cooldown.ready(now)) return null;
    if (Math.abs(ratio) < TRIGGER_RATIO) return null;
    if (Math.abs(rate) < MIN_RATE) return null;
    if (Math.sign(rate) !== Math.sign(ratio)) return null;

    this.cooldown.arm(now);
    this.baseline = span;

    const confidence = Math.min(1, Math.abs(ratio) / (TRIGGER_RATIO * 2));
    return makeEvent(ratio > 0 ? 'pull' : 'push', hand, confidence, now, Math.abs(ratio));
  }

  reset(): void {
    this.baseline = 0;
    this.strokeLock = false;
    this.cooldown.reset();
  }
}
