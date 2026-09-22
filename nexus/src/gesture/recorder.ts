import type { HandLandmarkerResult } from '@mediapipe/tasks-vision';
import { feedFrame, muteCamera } from './devFeed';

/**
 * Capture live landmarks, then replay them.
 *
 * Thresholds written from anatomy alone tend to describe the gesture the
 * author imagined rather than the one the camera actually resolves. A snap
 * lasts a few tens of milliseconds; at thirty frames a second the sensor may
 * see three frames of it, or one. The only way to know is to record a real
 * hand doing it and look at what came back.
 *
 * A recording is also a fixture: once captured it replays through the live
 * pipeline exactly like a synthetic scenario, so a detector tuned against it
 * can be re-checked later without anyone raising a hand.
 *
 * Development only.
 */

export interface RecordedFrame {
  /** Milliseconds since the recording started. */
  t: number;
  /** One entry per hand, each 21 landmarks of {x, y, z}. */
  hands: Array<Array<{ x: number; y: number; z: number }>>;
  handedness: string[];
}

export interface Recording {
  frames: RecordedFrame[];
  startedAt: number;
  label: string;
}

let active: Recording | null = null;
let stopAt = 0;
const shelf = new Map<string, Recording>();

/**
 * Captures outlive the page. A recording of a real hand is expensive to make
 * -- somebody has to be sitting there doing the gesture -- and editing a
 * detector reloads the page, which is precisely when the recording is needed
 * most. Coordinates are rounded to four decimals, which is far finer than the
 * landmarks are accurate and keeps a ten-second take near 150KB.
 */
const STORE_KEY = 'nexus.gesture.takes';

function round(v: number): number {
  return Math.round(v * 1e4) / 1e4;
}

function persist(): void {
  try {
    const flat: Record<string, Recording> = {};
    for (const [key, take] of shelf) {
      flat[key] = {
        ...take,
        frames: take.frames.map((f) => ({
          t: Math.round(f.t),
          handedness: f.handedness,
          hands: f.hands.map((h) => h.map((p) => ({ x: round(p.x), y: round(p.y), z: round(p.z) }))),
        })),
      };
    }
    localStorage.setItem(STORE_KEY, JSON.stringify(flat));
  } catch {
    // A full quota is not worth failing a recording over.
  }
}

function restore(): void {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return;
    const flat = JSON.parse(raw) as Record<string, Recording>;
    for (const [key, take] of Object.entries(flat)) shelf.set(key, take);
  } catch {
    // Corrupt or absent: start empty rather than break tracking.
  }
}

let restored = false;

function ensureRestored(): void {
  if (restored || typeof localStorage === 'undefined') return;
  restored = true;
  restore();
}

export function startRecording(label: string, ms: number): void {
  active = { frames: [], startedAt: performance.now(), label };
  stopAt = active.startedAt + ms;
}

export function recording(): boolean {
  return active !== null;
}

/** Called from the tracking loop for every live frame. Cheap when idle. */
export function captureFrame(result: HandLandmarkerResult, now: number): void {
  if (!active) return;
  if (now > stopAt) {
    shelf.set(active.label, active);
    active = null;
    persist();
    return;
  }
  active.frames.push({
    t: now - active.startedAt,
    hands: (result.landmarks ?? []).map((hand) =>
      hand.map((p) => ({ x: p.x, y: p.y, z: p.z ?? 0 })),
    ),
    handedness: (result.handedness ?? []).map((h) => h[0]?.categoryName ?? '?'),
  });
}

export function takeRecording(label: string): Recording | null {
  ensureRestored();
  return shelf.get(label) ?? null;
}

export function recordingLabels(): string[] {
  ensureRestored();
  return [...shelf.keys()];
}

export function forgetRecording(label: string): void {
  ensureRestored();
  shelf.delete(label);
  persist();
}

/**
 * Replay a recording through the live pipeline at its original cadence, so
 * detectors see the same timing the camera produced.
 */
export async function replayRecording(label: string): Promise<number> {
  ensureRestored();
  const take = shelf.get(label);
  if (!take || take.frames.length === 0) return 0;

  muteCamera(true);
  try {
    const t0 = performance.now();
    let played = 0;
    for (const frame of take.frames) {
      const due = t0 + frame.t;
      const waitFor = due - performance.now();
      if (waitFor > 0) await sleep(waitFor);
      feedFrame(toResult(frame), performance.now());
      played++;
    }
    return played;
  } finally {
    muteCamera(false);
  }
}

function toResult(frame: RecordedFrame): HandLandmarkerResult {
  const landmarks = frame.hands.map((hand) => hand.map((p) => ({ ...p, visibility: 1 })));
  const handedness = frame.handedness.map((name, i) => [
    { index: i, score: 0.98, categoryName: name, displayName: '' },
  ]);
  return { landmarks, worldLandmarks: landmarks, handedness, handednesses: handedness } as unknown as HandLandmarkerResult;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
