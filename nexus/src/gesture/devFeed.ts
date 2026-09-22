import type { HandLandmarkerResult } from '@mediapipe/tasks-vision';

/**
 * Test seam for the tracking pipeline.
 *
 * Hand tracking is the one subsystem that cannot be exercised without a human
 * being physically present, which means the gesture detectors -- Schmitt
 * triggers, cooldowns, the one-euro filter, hand-span normalisation -- would
 * otherwise ship having never run outside a wave of someone's hand.
 *
 * Registering the live loop's publish step here lets a synthetic landmark
 * sequence travel the real path: the same GestureEngine instance, the same
 * filters, the same runtime and the same bus. Only the camera is replaced.
 *
 * Development only; the registrar is a no-op in production builds.
 */

export type FramePublisher = (result: HandLandmarkerResult, now: number) => void;

let publisher: FramePublisher | null = null;
let muted = false;

/**
 * While a rehearsal plays, live camera frames must not reach the engine.
 * A camera pointed at an empty room publishes "no hands" thirty times a
 * second, and interleaving that with injected frames would make the engine
 * lose and reacquire the synthetic hand between every step of the movement.
 */
export function muteCamera(value: boolean): void {
  muted = value;
}

export function cameraMuted(): boolean {
  return muted;
}

export function registerFramePublisher(fn: FramePublisher | null): void {
  if (process.env.NODE_ENV === 'production') return;
  publisher = fn;
}

export function feedFrame(result: HandLandmarkerResult, now: number): boolean {
  if (!publisher) return false;
  publisher(result, now);
  return true;
}
