import type { GestureEvent } from '../types';
import { Cooldown, SampleRing, makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Circle — reserved for the phase-two AI surface.
 *
 * Detected by accumulating signed angle about the stroke's own centroid. A
 * genuine circle sweeps a large consistent angle at a roughly constant radius;
 * scribbles and back-and-forth motion cancel out because the signed sum, not
 * the absolute sum, is what has to clear the threshold.
 */
const WINDOW_MS = 1400;
const MIN_SWEEP = Math.PI * 1.55; // ~280 degrees
const MIN_RADIUS = 0.045;
const MAX_RADIUS_SPREAD = 0.55; // stddev / mean
const COOLDOWN_MS = 1500;

export class CircleDetector implements Detector {
  readonly id = 'circle';
  private ring = new SampleRing(56);
  private cooldown = new Cooldown(COOLDOWN_MS);

  update({ hand, now, grabbing }: DetectorContext): GestureEvent | null {
    if (grabbing) {
      this.ring.clear();
      return null;
    }
    this.ring.push(hand.palm.x, hand.palm.y, now);
    if (!this.cooldown.ready(now) || this.ring.size < 16) return null;

    // Collect the samples inside the window.
    let first = -1;
    for (let i = 0; i < this.ring.size; i++) {
      if (now - this.ring.at(i).t <= WINDOW_MS) {
        first = i;
        break;
      }
    }
    if (first < 0) return null;
    const n = this.ring.size - first;
    if (n < 14) return null;

    let cx = 0;
    let cy = 0;
    for (let i = first; i < this.ring.size; i++) {
      const s = this.ring.at(i);
      cx += s.x;
      cy += s.y;
    }
    cx /= n;
    cy /= n;

    let sweep = 0;
    let radiusSum = 0;
    let radiusSq = 0;
    let prevAngle = 0;
    for (let i = first; i < this.ring.size; i++) {
      const s = this.ring.at(i);
      const dx = s.x - cx;
      const dy = s.y - cy;
      const r = Math.hypot(dx, dy);
      radiusSum += r;
      radiusSq += r * r;
      const a = Math.atan2(dy, dx);
      if (i > first) {
        let d = a - prevAngle;
        if (d > Math.PI) d -= Math.PI * 2;
        else if (d < -Math.PI) d += Math.PI * 2;
        sweep += d;
      }
      prevAngle = a;
    }

    const meanR = radiusSum / n;
    if (meanR < MIN_RADIUS) return null;
    const variance = Math.max(0, radiusSq / n - meanR * meanR);
    if (Math.sqrt(variance) / meanR > MAX_RADIUS_SPREAD) return null;
    if (Math.abs(sweep) < MIN_SWEEP) return null;

    this.cooldown.arm(now);
    this.ring.clear();
    const confidence = Math.min(1, Math.abs(sweep) / (Math.PI * 2));
    return makeEvent('circle', hand, confidence, now, sweep);
  }

  reset(): void {
    this.ring.clear();
    this.cooldown.reset();
  }
}
