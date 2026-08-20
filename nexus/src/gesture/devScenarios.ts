import type { HandLandmarkerResult, NormalizedLandmark } from '@mediapipe/tasks-vision';
import { LM } from './landmarks';
import { feedFrame, muteCamera } from './devFeed';

/**
 * Synthetic hands, for rehearsing gestures without a camera.
 *
 * The detectors are the least testable code here: every threshold, Schmitt
 * trigger and cooldown only fires when a real hand moves a certain way in
 * front of a real lens. Building a hand out of arithmetic makes those paths
 * reproducible -- a swipe that fires here fires the same way every run, and a
 * threshold that drifts out of reach shows up immediately instead of at the
 * next demo.
 *
 * The poses are deliberately crude. They are not trying to look like a hand;
 * they are trying to produce the handful of ratios the detectors actually
 * measure: span, finger extension, thumb-index gap, palm velocity.
 *
 * Development only.
 */

export interface HandPose {
  /** Palm centre in image space, 0..1. */
  cx: number;
  cy: number;
  /** Wrist -> middle-MCP distance. Every measurement normalises by this. */
  span: number;
  /** Extension per finger: index, middle, ring, pinky. 0 curled, 1 straight. */
  fingers: [number, number, number, number];
  /** Thumb-tip to index-tip gap, in spans. Below ~0.28 reads as a pinch. */
  thumbGap: number;
  z: number;
}

export const OPEN_PALM: HandPose = {
  cx: 0.5, cy: 0.5, span: 0.16, fingers: [1, 1, 1, 1], thumbGap: 1.1, z: 0,
};

export const FIST: HandPose = { ...OPEN_PALM, fingers: [0, 0, 0, 0], thumbGap: 0.75 };
export const PINCHED: HandPose = { ...OPEN_PALM, fingers: [0.75, 0.3, 0.25, 0.25], thumbGap: 0.18 };
export const POINTING: HandPose = { ...OPEN_PALM, fingers: [1, 0.05, 0.05, 0.05], thumbGap: 0.9 };

/** Finger length from MCP to tip, in spans, at full extension. */
const FINGER_LEN = 1.25;
/** Lateral offset of each MCP from the middle knuckle, in spans. */
const MCP_X = [-0.45, 0, 0.42, 0.78];
const FINGER_IDS = [
  [LM.INDEX_MCP, LM.INDEX_PIP, LM.INDEX_DIP, LM.INDEX_TIP],
  [LM.MIDDLE_MCP, LM.MIDDLE_PIP, LM.MIDDLE_DIP, LM.MIDDLE_TIP],
  [LM.RING_MCP, LM.RING_PIP, LM.RING_DIP, LM.RING_TIP],
  [LM.PINKY_MCP, LM.PINKY_PIP, LM.PINKY_DIP, LM.PINKY_TIP],
] as const;

/**
 * Build one hand. The palm sits upright with fingers pointing up the frame
 * (-y), which is how a hand held toward the camera actually lands.
 */
export function buildHand(pose: HandPose): NormalizedLandmark[] {
  const pts: NormalizedLandmark[] = Array.from({ length: 21 }, () => ({
    x: 0,
    y: 0,
    z: pose.z,
    visibility: 1,
  }));
  const s = pose.span;
  const put = (i: number, x: number, y: number, z = pose.z) => {
    pts[i] = { x: pose.cx + x * s, y: pose.cy + y * s, z, visibility: 1 };
  };

  // Wrist half a span below the knuckle line, so wrist->middle-MCP == span.
  put(LM.WRIST, 0, 0.5);

  let indexTip = { x: 0, y: 0 };
  for (let f = 0; f < 4; f++) {
    const [mcp, pip, dip, tip] = FINGER_IDS[f]!;
    const ext = pose.fingers[f]!;
    const x = MCP_X[f]!;
    put(mcp, x, -0.5);
    // A curled finger folds its tip back toward the knuckle rather than
    // shrinking in place: that is what drives extension toward zero.
    const reach = FINGER_LEN * ext;
    put(pip, x, -0.5 - reach * 0.42);
    put(dip, x, -0.5 - reach * 0.74);
    put(tip, x, -0.5 - reach);
    if (f === 0) indexTip = { x, y: -0.5 - reach };
  }

  // The thumb is placed relative to the index tip, because the only thing any
  // detector asks of it is how far it sits from that point.
  const gap = pose.thumbGap;
  const tx = indexTip.x - gap * 0.72;
  const ty = indexTip.y + gap * 0.69;
  put(LM.THUMB_CMC, -0.55, 0.25);
  put(LM.THUMB_MCP, -0.72, -0.02);
  put(LM.THUMB_IP, (tx - 0.72) / 2, (ty - 0.02) / 2);
  put(LM.THUMB_TIP, tx, ty);
  return pts;
}

/**
 * Wrap poses as a MediaPipe result. `x` is mirrored back here so that a pose
 * authored in scene coordinates arrives the right way round after the engine
 * applies its own mirror.
 */
export function buildFrame(poses: HandPose[]): HandLandmarkerResult {
  const landmarks = poses.map((p) =>
    buildHand(p).map((l) => ({ ...l, x: 1 - l.x })),
  );
  return {
    landmarks,
    worldLandmarks: landmarks,
    handedness: poses.map((_, i) => [
      { index: i, score: 0.98, categoryName: i === 0 ? 'Left' : 'Right', displayName: '' },
    ]),
    handednesses: poses.map((_, i) => [
      { index: i, score: 0.98, categoryName: i === 0 ? 'Left' : 'Right', displayName: '' },
    ]),
  } as unknown as HandLandmarkerResult;
}

export type Scenario = (t: number) => HandPose[];

export interface Rehearsal {
  /** Duration of the movement itself. */
  ms: number;
  play: Scenario;
  /**
   * How long to hold the opening pose before moving. Filters and the depth
   * baseline need this to converge -- but an open palm held longer than the
   * palm-hold threshold freezes the world, which locks out the very detectors
   * some of these scenarios are trying to reach, so those settle briefly.
   */
  settle?: number;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/**
 * Each scenario is a function of normalised progress, sampled at camera rate.
 * Durations are chosen to clear the detector windows with a little margin --
 * a swipe has 260ms to travel, so it is driven over 240.
 */
export const SCENARIOS: Record<string, Rehearsal> = {
  idle: { ms: 700, play: () => [OPEN_PALM] },

  swipe_left: {
    ms: 240,
    settle: 300,
    play: (t) => [{ ...OPEN_PALM, cx: lerp(0.72, 0.28, t) }],
  },
  swipe_right: {
    ms: 240,
    settle: 300,
    play: (t) => [{ ...OPEN_PALM, cx: lerp(0.28, 0.72, t) }],
  },

  pinch: {
    ms: 400,
    play: (t) => [t < 0.35 ? OPEN_PALM : PINCHED],
  },

  release: {
    ms: 600,
    play: (t) => (t < 0.5 ? [PINCHED] : [{ ...OPEN_PALM, cx: 0.5 + (t - 0.5) * 0.5 }]),
  },

  palm_hold: { ms: 900, play: () => [OPEN_PALM] },

  // A hand nearing the camera grows, and the engine reads growth as `pull`.
  pull: {
    ms: 500,
    settle: 200,
    play: (t) => [{ ...OPEN_PALM, span: lerp(0.16, 0.26, t) }],
  },
  push: {
    ms: 500,
    settle: 200,
    // The span filter absorbs a good part of a fast excursion, so a push has
    // to travel further than the detector's nominal 19% to read as one --
    // which is what a real hand does anyway.
    play: (t) => [{ ...OPEN_PALM, span: lerp(0.16, 0.092, t) }],
  },

  point: { ms: 500, play: () => [POINTING] },

  fist: { ms: 500, play: () => [FIST] },

  circle: {
    ms: 1200,
    // The detector wants ~280 degrees inside a 1400ms window, so a stationary
    // settle would eat the budget. Start on the circle and keep moving.
    settle: 100,
    play: (t) => {
      const a = t * Math.PI * 2.2;
      return [{ ...POINTING, cx: 0.5 + Math.cos(a) * 0.13, cy: 0.5 + Math.sin(a) * 0.13 }];
    },
  },

  // The spread dial only engages while BOTH hands pinch: it is a grab, not a
  // wave. Two open palms held apart mean something else entirely (select).
  two_hand_spread: {
    ms: 1000,
    settle: 400,
    play: (t) => {
      const half = lerp(0.10, 0.27, t);
      return [
        { ...PINCHED, cx: 0.5 - half },
        { ...PINCHED, cx: 0.5 + half },
      ];
    },
  },
  two_hand_gather: {
    ms: 1000,
    settle: 400,
    play: (t) => {
      const half = lerp(0.27, 0.10, t);
      return [
        { ...PINCHED, cx: 0.5 - half },
        { ...PINCHED, cx: 0.5 + half },
      ];
    },
  },

  two_hand_zoom: {
    ms: 900,
    play: (t) => {
      const half = lerp(0.09, 0.26, t);
      return [
        { ...OPEN_PALM, cx: 0.5 - half },
        { ...OPEN_PALM, cx: 0.5 + half },
      ];
    },
  },
  two_hand_close: {
    ms: 900,
    play: (t) => {
      const half = lerp(0.26, 0.09, t);
      return [
        { ...OPEN_PALM, cx: 0.5 - half },
        { ...OPEN_PALM, cx: 0.5 + half },
      ];
    },
  },
};

const FRAME_MS = 33;
/**
 * Long enough for the engine to retire every hand it was tracking. Without
 * this a rehearsal inherits whatever was in front of the lens a moment ago --
 * live filter state, a depth baseline, a half-finished pinch -- and the first
 * synthetic frame reads as a violent change of pose rather than a new hand.
 */
const CLEAR_MS = 420;

/**
 * Replay a scenario through the live pipeline in real time. Real time matters:
 * every detector measures speed and dwell against the clock, so replaying
 * faster than a camera would invent motion that no hand could produce.
 */
export async function rehearse(name: string, settleMs?: number): Promise<boolean> {
  const scenario = SCENARIOS[name];
  if (!scenario) throw new Error(`unknown scenario: ${name}`);

  muteCamera(true);
  try {
    return await play(scenario, settleMs ?? scenario.settle ?? 500);
  } finally {
    muteCamera(false);
  }
}

async function play(scenario: Rehearsal, settleMs: number): Promise<boolean> {
  // Empty the engine first, so a rehearsal plays the same whether or not
  // somebody happens to be sitting in front of the camera. Without this the
  // synthetic hand inherits a real one's slot: its filters keep converging
  // from the live values and its depth baseline is somebody else's.
  const clearFrames = Math.round(CLEAR_MS / FRAME_MS);
  for (let i = 0; i < clearFrames; i++) {
    // A missing publisher means tracking is not running. Returning quietly
    // would let the whole rehearsal report "no gestures fired", which reads
    // as a detector failure rather than the setup problem it is.
    if (!feedFrame(buildFrame([]), performance.now())) {
      throw new Error('hand tracking is not running; enter hand mode first');
    }
    await sleep(FRAME_MS);
  }

  // Settle next: the filters and the depth baseline need a steady hand to
  // converge on before any motion means anything.
  const settleFrames = Math.round(settleMs / FRAME_MS);
  for (let i = 0; i < settleFrames; i++) {
    feedFrame(buildFrame(scenario.play(0)), performance.now());
    await sleep(FRAME_MS);
  }

  const frames = Math.max(2, Math.round(scenario.ms / FRAME_MS));
  for (let i = 0; i <= frames; i++) {
    feedFrame(buildFrame(scenario.play(i / frames)), performance.now());
    await sleep(FRAME_MS);
  }
  return true;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
