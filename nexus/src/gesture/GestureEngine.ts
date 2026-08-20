import type { HandLandmarkerResult } from '@mediapipe/tasks-vision';
import type { GestureEvent, HandFrame, Handedness, Posture } from './types';
import {
  apparentSize,
  isPointing,
  opennessRatio,
  palmCentre,
  pinchStrength,
} from './landmarks';
import { OneEuro, OneEuro2 } from './filters';
import { PinchDetector } from './detectors/pinch';
import { SwipeDetector } from './detectors/swipe';
import { DepthDetector } from './detectors/depth';
import { PalmHoldDetector } from './detectors/palmHold';
import { CircleDetector } from './detectors/circle';
import { PostureDetector } from './detectors/posture';
import { TwoHandDetector } from './detectors/twoHand';
import type { DetectorContext } from './detectors/types';
import { clamp01 } from '@/core/math';

/**
 * The gesture engine.
 *
 * Turns raw landmark output into a stable per-frame posture plus a stream of
 * discrete events. Everything is preallocated: two hand slots, each owning its
 * own filters and detector instances, reused for the life of the session. The
 * hot path allocates nothing, so tracking never causes a GC hitch mid-gesture.
 */

const MAX_HANDS = 2;
/** Hands not seen for this long are considered gone and their state is reset. */
const LOST_MS = 320;

interface HandSlot {
  frame: HandFrame;
  palmFilter: OneEuro2;
  spanFilter: OneEuro;
  pinchFilter: OneEuro;
  opennessFilter: OneEuro;
  detectors: {
    pinch: PinchDetector;
    swipe: SwipeDetector;
    depth: DepthDetector;
    palmHold: PalmHoldDetector;
    circle: CircleDetector;
    posture: PostureDetector;
  };
  lastSeen: number;
  prevPalm: { x: number; y: number };
  prevSpan: number;
  active: boolean;
}

function makeSlot(): HandSlot {
  return {
    frame: {
      handedness: 'Right',
      landmarks: new Float32Array(63),
      palm: { x: 0.5, y: 0.5 },
      depth: 0.5,
      span: 0,
      pinch: 0,
      openness: 0,
      velocity: { x: 0, y: 0 },
      depthVelocity: 0,
      posture: 'neutral',
      pointing: false,
      score: 0,
      world: [0, 0, 0],
    },
    // Palm needs a low baseline cutoff (it must be rock-steady when held) but
    // a high beta so fast swipes are not smeared into non-events.
    palmFilter: new OneEuro2(1.1, 0.02),
    spanFilter: new OneEuro(0.9, 0.008),
    pinchFilter: new OneEuro(2.4, 0.02),
    opennessFilter: new OneEuro(1.8, 0.015),
    detectors: {
      pinch: new PinchDetector(),
      swipe: new SwipeDetector(),
      depth: new DepthDetector(),
      palmHold: new PalmHoldDetector(),
      circle: new CircleDetector(),
      posture: new PostureDetector(),
    },
    lastSeen: 0,
    prevPalm: { x: 0.5, y: 0.5 },
    prevSpan: 0,
    active: false,
  };
}

export interface EngineOutput {
  hands: HandFrame[];
  primary: HandFrame | null;
  posture: Posture;
  events: GestureEvent[];
  /** 0..1 quality of the current tracking solution. */
  confidence: number;
  /** Progress toward the palm-hold freeze, for the HUD ring. */
  freezeProgress: number;
  frozen: boolean;
  grabbing: boolean;
  /** Two-handed ring spread, 0.55..1.75. */
  spread: number;
  twoHanded: boolean;
}

const scratchPalm = { x: 0, y: 0 };

export class GestureEngine {
  private slots: HandSlot[] = Array.from({ length: MAX_HANDS }, makeSlot);
  private events: GestureEvent[] = [];
  private liveHands: HandFrame[] = [];
  private lastTick = 0;
  private grabbing = false;
  /** Operates across both slots, so it cannot live inside one. */
  private twoHand = new TwoHandDetector();

  /** Set by the interaction layer so navigation detectors stand down mid-grab. */
  setGrabbing(v: boolean): void {
    this.grabbing = v;
  }

  update(result: HandLandmarkerResult | null, now: number): EngineOutput {
    const dt = this.lastTick === 0 ? 1 / 60 : Math.min(0.25, (now - this.lastTick) / 1000);
    this.lastTick = now;
    this.events.length = 0;
    this.liveHands.length = 0;

    const detected = result?.landmarks?.length ?? 0;

    for (let i = 0; i < MAX_HANDS; i++) {
      const slot = this.slots[i]!;
      if (i < detected && result) {
        this.ingest(slot, result, i, dt, now);
        this.runDetectors(slot, dt, now);
        this.liveHands.push(slot.frame);
      } else if (slot.active && now - slot.lastSeen > LOST_MS) {
        this.retire(slot);
      }
    }

    // Two-handed pass, after the per-hand detectors have settled this frame.
    const two = this.twoHand.update(this.liveHands, now);
    if (two.event) this.events.push(two.event);

    const primary = this.pickPrimary();
    const palmHold = this.slots[0]!.detectors.palmHold;

    return {
      hands: this.liveHands,
      primary,
      posture: primary ? primary.posture : 'neutral',
      events: this.events,
      confidence: primary ? primary.score : 0,
      freezeProgress: palmHold.progress(now),
      frozen: this.slots.some((s) => s.active && s.detectors.palmHold.frozen),
      grabbing: this.slots.some((s) => s.active && s.detectors.pinch.held),
      spread: two.spread,
      twoHanded: two.engaged,
    };
  }

  private ingest(
    slot: HandSlot,
    result: HandLandmarkerResult,
    index: number,
    dt: number,
    now: number,
  ): void {
    const raw = result.landmarks[index]!;
    const l = slot.frame.landmarks;

    // Mirror x so the scene reads as a mirror, which is what every user
    // expects from a front-facing camera.
    for (let j = 0; j < 21; j++) {
      const p = raw[j]!;
      l[j * 3] = 1 - p.x;
      l[j * 3 + 1] = p.y;
      l[j * 3 + 2] = p.z ?? 0;
    }

    const category = result.handedness?.[index]?.[0];
    // Handedness is reported for the camera's view; mirroring flips it.
    const label: Handedness = category?.categoryName === 'Left' ? 'Right' : 'Left';
    slot.frame.handedness = label;
    slot.frame.score = category?.score ?? 0.5;

    palmCentre(l, scratchPalm);
    const wasActive = slot.active;
    if (!wasActive) {
      slot.palmFilter.reset();
      slot.spanFilter.reset();
      slot.pinchFilter.reset();
      slot.opennessFilter.reset();
      slot.prevPalm.x = scratchPalm.x;
      slot.prevPalm.y = scratchPalm.y;
      slot.prevSpan = apparentSize(l);
    }

    slot.palmFilter.filter(scratchPalm.x, scratchPalm.y, dt, slot.frame.palm);

    const rawSpan = apparentSize(l);
    const span = slot.spanFilter.filter(rawSpan, dt);
    slot.frame.span = span;
    // Map a plausible span range onto 0..1 for a readable depth axis.
    slot.frame.depth = clamp01((span - 0.08) / (0.34 - 0.08));

    slot.frame.pinch = clamp01(slot.pinchFilter.filter(pinchStrength(l), dt));
    slot.frame.openness = clamp01(slot.opennessFilter.filter(opennessRatio(l), dt));

    const invDt = 1 / Math.max(dt, 1e-4);
    slot.frame.velocity.x = (slot.frame.palm.x - slot.prevPalm.x) * invDt;
    slot.frame.velocity.y = (slot.frame.palm.y - slot.prevPalm.y) * invDt;
    slot.frame.depthVelocity = ((span - slot.prevSpan) / Math.max(span, 1e-4)) * invDt;

    slot.prevPalm.x = slot.frame.palm.x;
    slot.prevPalm.y = slot.frame.palm.y;
    slot.prevSpan = span;

    slot.frame.pointing = isPointing(l);
    slot.lastSeen = now;
    slot.active = true;

    if (!wasActive) {
      for (const d of Object.values(slot.detectors)) d.reset();
    }
  }

  private runDetectors(slot: HandSlot, dt: number, now: number): void {
    const ctx: DetectorContext = {
      hand: slot.frame,
      dt,
      now,
      grabbing: this.grabbing || slot.detectors.pinch.held,
    };

    // Posture runs first so downstream consumers see the settled posture.
    const posture = slot.detectors.posture.update(ctx);
    slot.frame.posture = slot.detectors.posture.posture;

    const pinch = slot.detectors.pinch.update(ctx);
    const palmHold = slot.detectors.palmHold.update(ctx);

    // While frozen the world is locked: navigation gestures are suppressed so
    // the user cannot accidentally spin out of a freeze with the same hand.
    const locked = slot.detectors.palmHold.frozen;
    const swipe = locked ? null : slot.detectors.swipe.update(ctx);
    const depth = locked ? null : slot.detectors.depth.update(ctx);
    const circle = locked ? null : slot.detectors.circle.update(ctx);

    for (const e of [pinch, palmHold, swipe, depth, circle, posture]) {
      if (e) this.events.push(e);
    }
  }

  private retire(slot: HandSlot): void {
    slot.active = false;
    slot.palmFilter.reset();
    slot.spanFilter.reset();
    slot.pinchFilter.reset();
    slot.opennessFilter.reset();
    for (const d of Object.values(slot.detectors)) d.reset();
  }

  private pickPrimary(): HandFrame | null {
    let best: HandFrame | null = null;
    let bestScore = -1;
    for (const slot of this.slots) {
      if (!slot.active) continue;
      // A pinching hand always wins - it is the one doing the work.
      const score = slot.frame.score + (slot.detectors.pinch.held ? 1 : 0);
      if (score > bestScore) {
        bestScore = score;
        best = slot.frame;
      }
    }
    return best;
  }

  reset(): void {
    this.twoHand.reset();
    for (const slot of this.slots) this.retire(slot);
    this.lastTick = 0;
    this.grabbing = false;
  }
}
