import type { GestureEvent, Posture } from '../types';
import { makeEvent, type Detector, type DetectorContext } from './types';

/**
 * Continuous hand posture with hysteresis, plus discrete open/closed events.
 * This is the signal the HUD reads out and the one the reticle changes shape on.
 */
const OPEN_ENTER = 0.66;
const OPEN_EXIT = 0.5;
const CLOSED_ENTER = 0.22;
const CLOSED_EXIT = 0.36;

export class PostureDetector implements Detector {
  readonly id = 'posture';
  private current: Posture = 'neutral';

  update({ hand, now }: DetectorContext): GestureEvent | null {
    const next = this.classify(hand.openness, hand.pinch, hand.posture === 'point');
    if (next === this.current) return null;
    const previous = this.current;
    this.current = next;

    if (next === 'open' && previous !== 'open') return makeEvent('open_hand', hand, hand.openness, now);
    if (next === 'closed' && previous !== 'closed')
      return makeEvent('closed_hand', hand, 1 - hand.openness, now);
    return null;
  }

  private classify(openness: number, pinch: number, pointing: boolean): Posture {
    if (pinch > 0.66) return 'pinch';
    if (pointing) return 'point';
    if (this.current === 'open') return openness < OPEN_EXIT ? 'neutral' : 'open';
    if (this.current === 'closed') return openness > CLOSED_EXIT ? 'neutral' : 'closed';
    if (openness >= OPEN_ENTER) return 'open';
    if (openness <= CLOSED_ENTER) return 'closed';
    return 'neutral';
  }

  get posture(): Posture {
    return this.current;
  }

  reset(): void {
    this.current = 'neutral';
  }
}
