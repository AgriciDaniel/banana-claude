import type { GestureEvent, HandFrame } from '../types';
import { Cooldown } from './types';
import { clamp } from '@/core/math';

/**
 * Two-handed interaction.
 *
 * Unlike every other detector this one cannot live in a hand slot, because its
 * entire subject is the RELATIONSHIP between two hands. It runs once per frame
 * over both, and it produces one continuous signal plus three discrete ones.
 *
 * The continuous signal is `spread`: the distance between the hands while both
 * are pinching, normalised against the distance at the moment the grab began.
 * Pull your hands apart and the ring opens out; bring them together and it
 * closes in. It is a physical dial, so it needs no threshold and no cooldown -
 * you simply stop when it looks right.
 *
 * The discrete signals fire at the ends of that travel, and once the user has
 * committed to one the gesture is latched until they release, so a wobble at
 * the threshold cannot fire "group" and "split" alternately.
 */

export type TwoHandKind = 'group' | 'split' | 'select';

export interface TwoHandOutput {
  /** 0.55..1.75 multiplier on the ring radius. 1 when not engaged. */
  spread: number;
  engaged: boolean;
  event: GestureEvent | null;
}

/** Below and above these ratios, the gesture has been committed to. */
const GROUP_AT = 0.62;
const SPLIT_AT = 1.5;
/** Both palms open and held wide, then closed: multi-select. */
const SELECT_HOLD_MS = 450;

export class TwoHandDetector {
  private baseline = 0;
  private engaged = false;
  private latched: TwoHandKind | null = null;
  private spread = 1;
  private openSince = 0;
  private cooldown = new Cooldown(700);

  update(hands: HandFrame[], now: number): TwoHandOutput {
    if (hands.length < 2) {
      this.reset();
      return { spread: 1, engaged: false, event: null };
    }

    const [a, b] = hands as [HandFrame, HandFrame];
    const separation = Math.hypot(a.palm.x - b.palm.x, a.palm.y - b.palm.y);
    const bothPinching = a.pinch > 0.6 && b.pinch > 0.6;
    const bothOpen = a.openness > 0.65 && b.openness > 0.65;

    // --- multi-select: two open palms, held ---------------------------------
    if (!bothPinching && bothOpen && separation > 0.22) {
      if (this.openSince === 0) this.openSince = now;
      else if (now - this.openSince > SELECT_HOLD_MS && this.cooldown.ready(now)) {
        this.openSince = 0;
        this.cooldown.arm(now);
        return {
          spread: this.spread,
          engaged: false,
          event: { kind: 'two_select', confidence: 1, at: now, hand: 'both', magnitude: separation },
        };
      }
    } else {
      this.openSince = 0;
    }

    // --- the spread dial ----------------------------------------------------
    if (!bothPinching) {
      if (this.engaged) this.reset();
      // Relax back to neutral rather than snapping, so letting go is gentle.
      this.spread += (1 - this.spread) * 0.08;
      return { spread: this.spread, engaged: false, event: null };
    }

    if (!this.engaged) {
      this.engaged = true;
      this.baseline = Math.max(0.04, separation);
      this.latched = null;
    }

    const ratio = separation / this.baseline;
    // Damped so tracking noise does not make the ring breathe.
    this.spread += (clamp(ratio, 0.55, 1.75) - this.spread) * 0.22;

    let event: GestureEvent | null = null;
    if (!this.latched && this.cooldown.ready(now)) {
      if (ratio <= GROUP_AT) this.latched = 'group';
      else if (ratio >= SPLIT_AT) this.latched = 'split';

      if (this.latched) {
        this.cooldown.arm(now);
        event = {
          kind: this.latched === 'group' ? 'two_group' : 'two_split',
          confidence: clamp(Math.abs(1 - ratio), 0, 1),
          at: now,
          hand: 'both',
          magnitude: ratio,
        };
      }
    }

    return { spread: this.spread, engaged: true, event };
  }

  reset(): void {
    this.engaged = false;
    this.latched = null;
    this.baseline = 0;
    this.openSince = 0;
  }
}
