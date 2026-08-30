import { proxy } from 'valtio';
import type { GestureEvent, GestureSnapshot, HandFrame } from '@/gesture/types';
import { MODULE_COUNT } from '@/config/modules';
import { TAU } from '@/core/math';

/**
 * The runtime bus.
 *
 * Values that change every frame live HERE, not in React state. The render
 * loop reads and writes this object directly at 60–120 Hz; the HUD samples it
 * on a throttled interval. Nothing in this file may cause a re-render on its
 * own — that is the entire point.
 *
 * `telemetry` is a valtio proxy because the HUD genuinely wants fine-grained
 * subscriptions to a handful of slow-moving numbers; everything hotter than
 * that is a plain mutable object.
 */

export interface CarouselRuntime {
  /** Current ring rotation in radians. */
  angle: number;
  /** Angular velocity, rad/s. Momentum lives here. */
  velocity: number;
  /** Snap target; null while free-spinning. */
  target: number | null;
  /** Slot index nearest the viewer. */
  frontIndex: number;
  /** Set while a swipe-driven snap is in flight. */
  settling: boolean;
  /** Radians per slot. */
  readonly step: number;
}

export interface PerfRuntime {
  fps: number;
  frameMs: number;
  gpuMs: number;
  drawCalls: number;
  triangles: number;
  programs: number;
  /** Frames since the last quality change — governor hysteresis. */
  sinceTierChange: number;
}

export interface PointerRuntime {
  /** Normalised device coordinates, -1..1. */
  ndcX: number;
  ndcY: number;
  down: boolean;
  /** Set when the pointer moved in the last 3 s — used to fade the fallback cursor. */
  active: boolean;
  lastMove: number;
}

export interface InteractionRuntime {
  /** World-space point the primary hand (or pointer) is aiming at. */
  aimX: number;
  aimY: number;
  aimZ: number;
  /** Card id currently grabbed. */
  grabbedId: string | null;
  /** Grab offset from card centre, world space. */
  grabOffset: [number, number, number];
  /** Depth push/pull accumulator while grabbing, -1..1. */
  depthAxis: number;
  /** Global freeze — palm-hold locks all drift. */
  frozen: boolean;
  frozenAt: number;
  /** Smoothed 0..1 blend of `frozen`, shared by every shader that slows down. */
  freezeBlend: number;
  /**
   * Two-handed spread. Multiplies the ring radius, so pulling both hands apart
   * physically opens the carousel out. 1 when no two-handed grab is active.
   */
  spread: number;
  /** True while both hands are pinching. */
  twoHanded: boolean;
  /** Seconds of scene time, scaled by the freeze. Shaders read THIS, not clock. */
  sceneTime: number;
}

export const carousel: CarouselRuntime = {
  angle: 0,
  velocity: 0,
  target: 0,
  frontIndex: 0,
  settling: false,
  step: TAU / MODULE_COUNT,
};

export const perf: PerfRuntime = {
  fps: 0,
  frameMs: 0,
  gpuMs: 0,
  drawCalls: 0,
  triangles: 0,
  programs: 0,
  sinceTierChange: 0,
};

export const pointer: PointerRuntime = {
  ndcX: 0,
  ndcY: 0,
  down: false,
  active: false,
  lastMove: 0,
};

export const interaction: InteractionRuntime = {
  aimX: 0,
  aimY: 0,
  aimZ: 0,
  grabbedId: null,
  grabOffset: [0, 0, 0],
  depthAxis: 0,
  frozen: false,
  frozenAt: 0,
  freezeBlend: 0,
  sceneTime: 0,
  spread: 1,
  twoHanded: false,
};

export const gestureSnapshot: GestureSnapshot = {
  hands: [] as HandFrame[],
  primary: null,
  posture: 'neutral',
  lastEvent: null as GestureEvent | null,
  confidence: 0,
  latency: 0,
  freezeProgress: 0,
  rate: 0,
};

/**
 * Slow-moving readouts the HUD subscribes to. Written by the sampler at ~10 Hz
 * so a 120 fps render loop never renders a React tree.
 */
export const telemetry = proxy({
  fps: 0,
  frameMs: 0,
  drawCalls: 0,
  triangles: 0,
  /** Translation key, resolved at render time. See hooks/useTelemetry.ts. */
  gestureKey: 'gesture.none',
  gestureConfidence: 0,
  handCount: 0,
  latency: 0,
  frozen: false,
  /** Module id; the HUD localises the name itself. */
  frontModuleId: '',
});

/** Reset everything that must not survive a hot reload or a re-entry. */
export function resetRuntime() {
  carousel.angle = 0;
  carousel.velocity = 0;
  carousel.target = 0;
  carousel.frontIndex = 0;
  carousel.settling = false;
  interaction.grabbedId = null;
  interaction.depthAxis = 0;
  interaction.frozen = false;
  interaction.freezeBlend = 0;
  interaction.spread = 1;
  interaction.twoHanded = false;
  interaction.sceneTime = 0;
  gestureSnapshot.hands = [];
  gestureSnapshot.primary = null;
  gestureSnapshot.lastEvent = null;
}

/**
 * Momentum handed from a released pinch to a card's rigid body.
 *
 * The interaction layer writes here; the card drains it on the next physics
 * frame. A map rather than a field on the card because the producer must not
 * need a reference to the consumer.
 */
export interface ReleaseImpulse {
  lin: [number, number, number];
  ang: [number, number, number];
}

export const pendingImpulses = new Map<string, ReleaseImpulse>();

/**
 * Assistant continuous state.
 *
 * Speech amplitude and the wake pulse change every frame, so by the Phase 1
 * rule they live here rather than in the assistant store. The scene reads them
 * directly in useFrame; nothing re-renders.
 */
/**
 * The place in the room the assistant is talking about.
 *
 * Written by whatever is currently holding content -- today the media stage --
 * and read by the figure, which turns and points at it. Deliberately a world
 * point rather than an id: the thing that indicates does not need to know what
 * kind of thing it is indicating, and a new kind of surface can claim the
 * assistant's attention tomorrow by writing three numbers here.
 *
 * `weight` is how much there is to indicate at all, 0..1. It falls to zero
 * when the stage empties, which is what lets the arm come back down.
 */
export const attention = {
  weight: 0,
  x: 0,
  y: 0,
  z: 0,
};

export const voice = {
  /** Speech loudness, 0..1. Drives the presence orb and the interface glow. */
  level: 0,
  /** Seconds since the last wake, or -1 when never woken. Drives the wave. */
  wakeAt: -1,
  /** Smoothed 0..1 blend of the awake state. */
  awakeBlend: 0,
};
