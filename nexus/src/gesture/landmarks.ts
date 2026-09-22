/**
 * MediaPipe hand landmark topology and the geometric primitives built on it.
 * Everything here is pure and allocation-free in the hot path.
 */

export const LM = {
  WRIST: 0,
  THUMB_CMC: 1,
  THUMB_MCP: 2,
  THUMB_IP: 3,
  THUMB_TIP: 4,
  INDEX_MCP: 5,
  INDEX_PIP: 6,
  INDEX_DIP: 7,
  INDEX_TIP: 8,
  MIDDLE_MCP: 9,
  MIDDLE_PIP: 10,
  MIDDLE_DIP: 11,
  MIDDLE_TIP: 12,
  RING_MCP: 13,
  RING_PIP: 14,
  RING_DIP: 15,
  RING_TIP: 16,
  PINKY_MCP: 17,
  PINKY_PIP: 18,
  PINKY_DIP: 19,
  PINKY_TIP: 20,
} as const;

/** Bone pairs for the 2D skeleton overlay. */
export const BONES: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];

const FINGER_CHAINS: ReadonlyArray<readonly [number, number, number]> = [
  [LM.INDEX_MCP, LM.INDEX_PIP, LM.INDEX_TIP],
  [LM.MIDDLE_MCP, LM.MIDDLE_PIP, LM.MIDDLE_TIP],
  [LM.RING_MCP, LM.RING_PIP, LM.RING_TIP],
  [LM.PINKY_MCP, LM.PINKY_PIP, LM.PINKY_TIP],
];

export const lmX = (l: Float32Array, i: number) => l[i * 3];
export const lmY = (l: Float32Array, i: number) => l[i * 3 + 1];
export const lmZ = (l: Float32Array, i: number) => l[i * 3 + 2];

export function dist2(l: Float32Array, a: number, b: number): number {
  const dx = lmX(l, a) - lmX(l, b);
  const dy = lmY(l, a) - lmY(l, b);
  return Math.hypot(dx, dy);
}

export function dist3(l: Float32Array, a: number, b: number): number {
  const dx = lmX(l, a) - lmX(l, b);
  const dy = lmY(l, a) - lmY(l, b);
  const dz = lmZ(l, a) - lmZ(l, b);
  return Math.hypot(dx, dy, dz);
}

/**
 * Scale-invariant reference length: wrist -> middle MCP.
 * Every other measurement is divided by this so gestures work at any distance.
 */
export function handSpan(l: Float32Array): number {
  return Math.max(1e-4, dist2(l, LM.WRIST, LM.MIDDLE_MCP));
}

/** Palm centroid — averaged over the four MCP joints and the wrist. */
export function palmCentre(l: Float32Array, out: { x: number; y: number }): void {
  const ids = [LM.WRIST, LM.INDEX_MCP, LM.MIDDLE_MCP, LM.RING_MCP, LM.PINKY_MCP];
  let x = 0;
  let y = 0;
  for (const i of ids) {
    x += lmX(l, i);
    y += lmY(l, i);
  }
  out.x = x / ids.length;
  out.y = y / ids.length;
}

/**
 * Pinch strength: thumb-tip to index-tip distance, normalised by hand span,
 * remapped so 1 = touching and 0 = comfortably apart.
 */
export function pinchStrength(l: Float32Array): number {
  const d = dist3(l, LM.THUMB_TIP, LM.INDEX_TIP) / handSpan(l);
  // 0.28 span = contact, 0.9 span = clearly open.
  const t = (0.9 - d) / (0.9 - 0.28);
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

/**
 * Openness: mean finger extension. A finger is "extended" when its tip is
 * further from the wrist than its PIP joint, scaled by span.
 */
export function opennessRatio(l: Float32Array): number {
  const span = handSpan(l);
  let sum = 0;
  for (const [, pip, tip] of FINGER_CHAINS) {
    const tipD = dist2(l, LM.WRIST, tip) / span;
    const pipD = dist2(l, LM.WRIST, pip) / span;
    const extension = (tipD - pipD) / 0.95; // ~0.95 span when fully extended
    sum += extension < 0 ? 0 : extension > 1 ? 1 : extension;
  }
  return sum / FINGER_CHAINS.length;
}

/**
 * Thumb-tip to middle-tip distance, in spans. This is the pair a snap loads,
 * as distinct from the thumb-index pair a pinch closes.
 */
export function snapGap(l: Float32Array): number {
  return dist3(l, LM.THUMB_TIP, LM.MIDDLE_TIP) / handSpan(l);
}

/**
 * How far the middle fingertip sits from the wrist, in spans. Extended it
 * reads ~1.4; folded against the base of the palm, ~0.65. Measured from the
 * wrist so that moving the hand across frame does not disturb it.
 */
export function middleReach(l: Float32Array): number {
  return dist2(l, LM.WRIST, LM.MIDDLE_TIP) / handSpan(l);
}

/** True when only the index finger is extended. */
export function isPointing(l: Float32Array): boolean {
  const span = handSpan(l);
  const index = dist2(l, LM.WRIST, LM.INDEX_TIP) / span;
  const middle = dist2(l, LM.WRIST, LM.MIDDLE_TIP) / span;
  const ring = dist2(l, LM.WRIST, LM.RING_TIP) / span;
  return index > 1.6 && middle < 1.25 && ring < 1.2;
}

/**
 * Apparent size of the hand across the frame — the depth proxy.
 * Uses wrist -> middle-tip so it survives a closed fist better than a bbox.
 */
export function apparentSize(l: Float32Array): number {
  return Math.max(dist2(l, LM.WRIST, LM.MIDDLE_MCP), dist2(l, LM.INDEX_MCP, LM.PINKY_MCP));
}
