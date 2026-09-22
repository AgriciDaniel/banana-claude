import type { GestureEvent, HandFrame } from '../types';

export interface DetectorContext {
  hand: HandFrame;
  /** Seconds since the previous detector tick. */
  dt: number;
  /** performance.now() of this tick. */
  now: number;
  /** True while a card is grabbed — several detectors stand down. */
  grabbing: boolean;
}

export interface Detector {
  readonly id: string;
  /** Returns an event on the frame it fires, otherwise null. */
  update(ctx: DetectorContext): GestureEvent | null;
  reset(): void;
}

/** Shared cooldown helper — every discrete detector needs one. */
export class Cooldown {
  private until = 0;
  constructor(private readonly ms: number) {}
  ready(now: number): boolean {
    return now >= this.until;
  }
  arm(now: number): void {
    this.until = now + this.ms;
  }
  reset(): void {
    this.until = 0;
  }
}

/** Fixed-capacity ring of timestamped 2D samples, allocation-free after construction. */
export class SampleRing {
  private xs: Float32Array;
  private ys: Float32Array;
  private ts: Float64Array;
  private head = 0;
  private count = 0;

  constructor(readonly capacity: number) {
    this.xs = new Float32Array(capacity);
    this.ys = new Float32Array(capacity);
    this.ts = new Float64Array(capacity);
  }

  push(x: number, y: number, t: number): void {
    this.xs[this.head] = x;
    this.ys[this.head] = y;
    this.ts[this.head] = t;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) this.count++;
  }

  get size(): number {
    return this.count;
  }

  /** i = 0 is the oldest retained sample. */
  at(i: number): { x: number; y: number; t: number } {
    const start = this.count === this.capacity ? this.head : 0;
    const idx = (start + i) % this.capacity;
    return { x: this.xs[idx], y: this.ys[idx], t: this.ts[idx] };
  }

  newest(): { x: number; y: number; t: number } | null {
    if (this.count === 0) return null;
    return this.at(this.count - 1);
  }

  /** Oldest sample no older than `ms` before now, or the oldest available. */
  oldestWithin(now: number, ms: number): { x: number; y: number; t: number } | null {
    if (this.count === 0) return null;
    for (let i = 0; i < this.count; i++) {
      const s = this.at(i);
      if (now - s.t <= ms) return s;
    }
    return this.at(this.count - 1);
  }

  clear(): void {
    this.head = 0;
    this.count = 0;
  }
}

export const makeEvent = (
  kind: GestureEvent['kind'],
  hand: HandFrame,
  confidence: number,
  now: number,
  magnitude?: number,
): GestureEvent => ({
  kind,
  confidence: confidence < 0 ? 0 : confidence > 1 ? 1 : confidence,
  at: now,
  hand: hand.handedness,
  magnitude,
});
