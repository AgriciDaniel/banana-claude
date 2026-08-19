export const TAU = Math.PI * 2;

export const clamp = (v: number, min: number, max: number) => (v < min ? min : v > max ? max : v);

export const clamp01 = (v: number) => clamp(v, 0, 1);

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

export const invLerp = (a: number, b: number, v: number) => (b === a ? 0 : (v - a) / (b - a));

export const mapRange = (v: number, inMin: number, inMax: number, outMin: number, outMax: number) =>
  lerp(outMin, outMax, clamp01(invLerp(inMin, inMax, v)));

export const smoothstep = (edge0: number, edge1: number, x: number) => {
  const t = clamp01((x - edge0) / (edge1 - edge0));
  return t * t * (3 - 2 * t);
};

/**
 * Frame-rate independent exponential approach.
 * `lambda` is the decay rate — higher converges faster.
 */
export const damp = (current: number, target: number, lambda: number, dt: number) =>
  lerp(current, target, 1 - Math.exp(-lambda * dt));

/** Wrap an angle into (-PI, PI]. */
export const wrapAngle = (a: number) => {
  let x = (a + Math.PI) % TAU;
  if (x < 0) x += TAU;
  return x - Math.PI;
};

/** Shortest signed rotation from `from` to `to`. */
export const angleDelta = (from: number, to: number) => wrapAngle(to - from);

/** Deterministic pseudo-random from a scalar seed — stable across reloads. */
export const hash11 = (seed: number) => {
  const x = Math.sin(seed * 127.1) * 43758.5453;
  return x - Math.floor(x);
};

/** Cheap 1D value noise; continuous, seeded, in [-1, 1]. */
export const noise1 = (x: number, seed = 0) => {
  const i = Math.floor(x);
  const f = x - i;
  const u = f * f * (3 - 2 * f);
  const a = hash11(i + seed * 31.7);
  const b = hash11(i + 1 + seed * 31.7);
  return lerp(a, b, u) * 2 - 1;
};

/** Rolling average with a fixed window; used by the FPS governor. */
export class RollingMean {
  private buf: Float32Array;
  private idx = 0;
  private filled = 0;
  private sum = 0;

  constructor(size: number) {
    this.buf = new Float32Array(size);
  }

  push(v: number): number {
    this.sum -= this.buf[this.idx];
    this.buf[this.idx] = v;
    this.sum += v;
    this.idx = (this.idx + 1) % this.buf.length;
    if (this.filled < this.buf.length) this.filled++;
    return this.mean;
  }

  get mean(): number {
    return this.filled === 0 ? 0 : this.sum / this.filled;
  }

  get saturated(): boolean {
    return this.filled === this.buf.length;
  }

  reset() {
    this.buf.fill(0);
    this.idx = 0;
    this.filled = 0;
    this.sum = 0;
  }
}
