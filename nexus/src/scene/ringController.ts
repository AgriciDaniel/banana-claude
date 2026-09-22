import { AngularSpring } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { MODULE_COUNT } from '@/config/modules';
import { angleForIndex, SLOT_STEP } from './cardMath';
import { carousel, interaction } from '@/stores/runtime';
import { bus } from '@/stores/bus';

/**
 * The ring.
 *
 * One angular spring is the entire carousel. Snapping, momentum, overshoot and
 * multi-step swipes all fall out of a single integrator rather than being
 * three separate systems fighting each other:
 *
 *   - the spring's TARGET is always a slot centre, so the ring can never rest
 *     between two cards;
 *   - a swipe moves the target one slot AND injects velocity, so a fast flick
 *     overshoots and settles back, exactly like a physical detent wheel;
 *   - stacked swipes just keep moving the target, so the momentum compounds.
 */

const spring = new AngularSpring(0, SPRINGS.carousel);

/** Unwrapped slot index the ring is heading for; may go negative or past N. */
let targetIndex = 0;
/** Suppresses input while the world is frozen. */
let locked = false;

export const ring = {
  get angle(): number {
    return spring.value;
  },

  get velocity(): number {
    return spring.velocity;
  },

  get targetIndex(): number {
    return ((targetIndex % MODULE_COUNT) + MODULE_COUNT) % MODULE_COUNT;
  },

  get settling(): boolean {
    return !spring.atRest;
  },

  setLocked(v: boolean): void {
    locked = v;
  },

  /**
   * Advance one slot. `power` scales the extra velocity injected on top of the
   * target change — a lazy swipe glides, a hard flick snaps and rings.
   */
  rotate(direction: -1 | 1, power = 1): void {
    if (locked) return;
    targetIndex += direction;
    spring.set(angleForIndex(targetIndex));
    spring.impulse(direction * SLOT_STEP * 1.35 * Math.min(power, 2.2));
    bus.emit('carousel:snap', { index: ring.targetIndex, direction });
  },

  /** Free spin — used by the pointer fallback while dragging the background. */
  spin(deltaRadians: number): void {
    if (locked) return;
    spring.value += deltaRadians;
    spring.velocity = deltaRadians * 22;
    spring.set(spring.target);
  },

  /** Called when a free spin ends: pick the slot the momentum is heading for. */
  release(): void {
    if (locked) return;
    // Project a short way ahead so a flick lands where it was aimed.
    const projected = spring.value + spring.velocity * 0.28;
    targetIndex = Math.round(-projected / SLOT_STEP);
    spring.set(angleForIndex(targetIndex));
  },

  /** Jump straight to a slot — used by keyboard navigation and deep links. */
  focus(index: number): void {
    const current = ring.targetIndex;
    let delta = index - current;
    // Always take the short way round the ring.
    if (delta > MODULE_COUNT / 2) delta -= MODULE_COUNT;
    if (delta < -MODULE_COUNT / 2) delta += MODULE_COUNT;
    targetIndex += delta;
    spring.set(angleForIndex(targetIndex));
  },

  /** Integrate one frame and publish to the runtime bus. */
  update(dt: number): void {
    // Freezing thickens time rather than stopping it: the ring keeps drifting
    // to a halt instead of jamming, which reads as intent, not as a crash.
    const scale = 1 - interaction.freezeBlend * 0.94;
    spring.update(dt * scale);

    carousel.angle = spring.value;
    carousel.velocity = spring.velocity;
    carousel.target = spring.target;
    carousel.settling = !spring.atRest;
    carousel.frontIndex = ring.targetIndex;
  },

  reset(): void {
    targetIndex = 0;
    spring.jump(0);
    locked = false;
  },
};
