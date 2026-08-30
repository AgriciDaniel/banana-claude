import type { Vec3 } from '@/core/types';

/**
 * Damped harmonic oscillators.
 *
 * NEXUS has no linear interpolation in any user-visible motion. Every value
 * that moves — position, rotation, scale, glow, ring angle — is integrated
 * through one of these. Overshoot, momentum and elasticity are properties of
 * the integrator, not keyframes bolted on afterwards.
 *
 * Integration is semi-implicit Euler with adaptive substepping: stable at
 * stiffness values high enough to feel instant, without exploding on a
 * dropped frame or a backgrounded tab.
 */

export interface SpringConfig {
  /** Restoring force. Higher = faster convergence. */
  stiffness: number;
  /** Velocity damping. Below the critical value the spring overshoots. */
  damping: number;
  /** Inertia. Higher = more momentum, more lag behind the target. */
  mass: number;
  /** Below this displacement AND velocity the spring is considered at rest. */
  precision: number;
}

export const springConfig = (
  stiffness: number,
  damping: number,
  mass = 1,
  precision = 0.0005,
): SpringConfig => ({ stiffness, damping, mass, precision });

/** Largest step the integrator will take; anything bigger is subdivided. */
const MAX_STEP = 1 / 120;
/** Guard against tab-restore deltas nuking the simulation. */
const MAX_DELTA = 0.1;

export class Spring {
  value: number;
  target: number;
  velocity = 0;
  config: SpringConfig;
  protected resting = true;

  constructor(initial: number, config: SpringConfig) {
    this.value = initial;
    this.target = initial;
    this.config = config;
  }

  set(target: number): this {
    if (target !== this.target) {
      this.target = target;
      this.resting = false;
    }
    return this;
  }

  /** Teleport without integration — used on mount and on hard resets. */
  jump(value: number): this {
    this.value = value;
    this.target = value;
    this.velocity = 0;
    this.resting = true;
    return this;
  }

  /** Swap the motion signature without disturbing the current state. */
  configure(config: SpringConfig): this {
    this.config = config;
    return this;
  }

  /** Inject velocity — how a released pinch hands its momentum to the card. */
  impulse(v: number): this {
    this.velocity += v;
    this.resting = false;
    return this;
  }

  get atRest(): boolean {
    return this.resting;
  }

  update(dt: number): number {
    if (this.resting) return this.value;
    const clamped = dt > MAX_DELTA ? MAX_DELTA : dt;
    const steps = Math.max(1, Math.ceil(clamped / MAX_STEP));
    const h = clamped / steps;
    const { stiffness, damping, mass, precision } = this.config;

    for (let i = 0; i < steps; i++) {
      const displacement = this.value - this.target;
      const accel = (-stiffness * displacement - damping * this.velocity) / mass;
      this.velocity += accel * h;
      this.value += this.velocity * h;
    }

    if (
      Math.abs(this.value - this.target) < precision &&
      Math.abs(this.velocity) < precision * 60
    ) {
      this.value = this.target;
      this.velocity = 0;
      this.resting = true;
    }
    return this.value;
  }
}

/** Three independent springs sharing one config. Allocation-free per frame. */
export class Spring3 {
  readonly x: Spring;
  readonly y: Spring;
  readonly z: Spring;

  constructor(initial: Vec3, config: SpringConfig) {
    this.x = new Spring(initial[0], config);
    this.y = new Spring(initial[1], config);
    this.z = new Spring(initial[2], config);
  }

  set(x: number, y: number, z: number): this {
    this.x.set(x);
    this.y.set(y);
    this.z.set(z);
    return this;
  }

  setVec(v: Vec3): this {
    return this.set(v[0], v[1], v[2]);
  }

  jump(x: number, y: number, z: number): this {
    this.x.jump(x);
    this.y.jump(y);
    this.z.jump(z);
    return this;
  }

  impulse(x: number, y: number, z: number): this {
    this.x.impulse(x);
    this.y.impulse(y);
    this.z.impulse(z);
    return this;
  }

  configure(config: SpringConfig): this {
    this.x.config = config;
    this.y.config = config;
    this.z.config = config;
    return this;
  }

  update(dt: number): this {
    this.x.update(dt);
    this.y.update(dt);
    this.z.update(dt);
    return this;
  }

  get atRest(): boolean {
    return this.x.atRest && this.y.atRest && this.z.atRest;
  }

  get speed(): number {
    return Math.hypot(this.x.velocity, this.y.velocity, this.z.velocity);
  }
}

/**
 * Angular spring that always travels the short way round the circle.
 *
 * The carousel and every card's yaw run on this. Displacement is folded into
 * (-PI, PI] before integration, so a target of 0 and a value of 6.28 are one
 * step apart rather than a full revolution — the ring can spin forever without
 * accumulating error or unwinding on the way back.
 */
export class AngularSpring extends Spring {
  override update(dt: number): number {
    if (this.resting) return this.value;
    const clamped = dt > MAX_DELTA ? MAX_DELTA : dt;
    const steps = Math.max(1, Math.ceil(clamped / MAX_STEP));
    const h = clamped / steps;
    const { stiffness, damping, mass, precision } = this.config;
    const TAU = Math.PI * 2;

    for (let i = 0; i < steps; i++) {
      let displacement = (this.value - this.target) % TAU;
      if (displacement > Math.PI) displacement -= TAU;
      else if (displacement < -Math.PI) displacement += TAU;

      const accel = (-stiffness * displacement - damping * this.velocity) / mass;
      this.velocity += accel * h;
      this.value += this.velocity * h;
    }

    let remaining = (this.value - this.target) % TAU;
    if (remaining > Math.PI) remaining -= TAU;
    else if (remaining < -Math.PI) remaining += TAU;

    if (Math.abs(remaining) < precision && Math.abs(this.velocity) < precision * 60) {
      this.value -= remaining;
      this.velocity = 0;
      this.resting = true;
    }
    return this.value;
  }
}
