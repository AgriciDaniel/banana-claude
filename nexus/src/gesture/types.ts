import type { Vec3 } from '@/core/types';

export type Handedness = 'Left' | 'Right';

/** Continuous, per-frame gesture posture. Always present while a hand is seen. */
export type Posture = 'open' | 'closed' | 'pinch' | 'point' | 'neutral';

/** Discrete, fired-once gesture events. */
export type GestureKind =
  | 'none'
  | 'pinch_start'
  | 'pinch_end'
  | 'swipe_left'
  | 'swipe_right'
  | 'pull'
  | 'push'
  | 'palm_hold'
  | 'palm_release'
  | 'open_hand'
  | 'closed_hand'
  | 'circle'
  // --- two-handed --------------------------------------------------------
  /** Both hands pinched and drawn together. */
  | 'two_group'
  /** Both hands pinched and drawn apart. */
  | 'two_split'
  /** Both palms open and held wide. */
  | 'two_select';

export interface Point2 {
  x: number;
  y: number;
}

/** One tracked hand, normalised. Coordinates are 0..1 in video space, */
/** already mirrored so they read as a front-facing mirror. */
export interface HandFrame {
  handedness: Handedness;
  /** 21 landmarks, flattened xyz. Video space, mirrored. */
  landmarks: Float32Array;
  /** Palm centre (mean of wrist + MCP joints). */
  palm: Point2;
  /** Palm depth proxy in [0,1]: derived from apparent hand span. */
  depth: number;
  /** Hand span in normalised units — the raw scale signal behind `depth`. */
  span: number;
  /** 0 = wide open, 1 = fully pinched. Normalised by hand span. */
  pinch: number;
  /** 0 = fist, 1 = fully splayed. */
  openness: number;
  /** Palm velocity in normalised units per second. */
  velocity: Point2;
  /** Rate of change of `depth`, per second. */
  depthVelocity: number;
  posture: Posture;
  /**
   * Whether only the index finger is extended, recomputed every frame.
   * Kept apart from `posture` because posture is a hysteretic state: folding
   * pointing into it directly meant a single pointing frame could latch the
   * hand into that posture for as long as it stayed tracked.
   */
  pointing: boolean;
  /** Tracking confidence reported by the detector. */
  score: number;
  /** Palm projected onto the interaction plane in world space. */
  world: Vec3;
}

export interface GestureEvent {
  kind: GestureKind;
  confidence: number;
  /** performance.now() at emission. */
  at: number;
  hand: Handedness | 'both';
  /** Optional magnitude — swipe speed, pull distance, etc. */
  magnitude?: number;
}

/** Live per-frame snapshot shared with the render loop. */
export interface GestureSnapshot {
  hands: HandFrame[];
  /** Dominant hand: the highest-confidence hand, or the pinching one. */
  primary: HandFrame | null;
  posture: Posture;
  /** Most recent discrete event and how long ago it fired. */
  lastEvent: GestureEvent | null;
  /** Rolling confidence of the whole pipeline, 0..1. */
  confidence: number;
  /** Detector latency in ms. */
  latency: number;
  /** 0..1 progress toward the palm-hold freeze. Drives the HUD ring. */
  freezeProgress: number;
  /** Detector frames per second — the tracking loop's own rate. */
  rate: number;
}
