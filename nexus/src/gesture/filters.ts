/**
 * One Euro filter.
 *
 * Landmark output is jittery at rest and laggy when smoothed with a fixed
 * low-pass. One Euro adapts its cutoff to speed: heavy smoothing while the
 * hand is still (kills tremor), light smoothing while it moves (keeps the
 * gesture responsive). This is the single biggest quality lever in the whole
 * tracking pipeline.
 *
 * Casiez, Roussel & Vogel, CHI 2012.
 */

class LowPass {
  private y = 0;
  private initialised = false;

  filter(x: number, alpha: number): number {
    if (!this.initialised) {
      this.y = x;
      this.initialised = true;
      return x;
    }
    this.y = alpha * x + (1 - alpha) * this.y;
    return this.y;
  }

  get value(): number {
    return this.y;
  }

  get ready(): boolean {
    return this.initialised;
  }

  reset(): void {
    this.initialised = false;
    this.y = 0;
  }
}

export class OneEuro {
  private xFilter = new LowPass();
  private dxFilter = new LowPass();
  private lastX = 0;
  private started = false;

  constructor(
    /** Baseline cutoff in Hz. Lower = smoother at rest. */
    private minCutoff = 1.2,
    /** How aggressively the cutoff opens up with speed. */
    private beta = 0.012,
    /** Cutoff for the derivative estimate. */
    private dCutoff = 1.0,
  ) {}

  filter(x: number, dt: number): number {
    if (dt <= 0 || !Number.isFinite(dt)) dt = 1 / 60;
    const rate = 1 / dt;

    const dx = this.started ? (x - this.lastX) * rate : 0;
    this.lastX = x;
    this.started = true;

    const edx = this.dxFilter.filter(dx, alpha(this.dCutoff, rate));
    const cutoff = this.minCutoff + this.beta * Math.abs(edx);
    return this.xFilter.filter(x, alpha(cutoff, rate));
  }

  /** Filtered derivative — a free, well-conditioned velocity signal. */
  get derivative(): number {
    return this.dxFilter.value;
  }

  reset(): void {
    this.xFilter.reset();
    this.dxFilter.reset();
    this.started = false;
    this.lastX = 0;
  }
}

function alpha(cutoff: number, rate: number): number {
  const tau = 1 / (2 * Math.PI * cutoff);
  const te = 1 / rate;
  return 1 / (1 + tau / te);
}

/** Convenience pair for 2D points. */
export class OneEuro2 {
  readonly x: OneEuro;
  readonly y: OneEuro;

  constructor(minCutoff = 1.2, beta = 0.012) {
    this.x = new OneEuro(minCutoff, beta);
    this.y = new OneEuro(minCutoff, beta);
  }

  filter(px: number, py: number, dt: number, out: { x: number; y: number }): void {
    out.x = this.x.filter(px, dt);
    out.y = this.y.filter(py, dt);
  }

  reset(): void {
    this.x.reset();
    this.y.reset();
  }
}
