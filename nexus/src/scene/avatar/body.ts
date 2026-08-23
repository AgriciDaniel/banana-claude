import {
  BoxGeometry,
  CapsuleGeometry,
  LatheGeometry,
  SphereGeometry,
  Vector2,
  type BufferGeometry,
} from 'three';

/**
 * The body, as profiles.
 *
 * The first figure was eleven capsules, and a capsule is the same width all the
 * way down. That is what made it read as an armature rather than as a person:
 * no shoulders, no waist, no calf, no wrist. Every part of a body that tells
 * you it is a body is a change in width.
 *
 * So the limbs and the trunk are lathes now -- a list of (radius, height)
 * points revolved around the bone's own axis. It costs the same to draw, it is
 * still generated at runtime with no asset to download, and it gives the one
 * thing capsules cannot: a silhouette.
 *
 * Every profile runs from the far end of the bone up to its joint at y = 0, so
 * a limb geometry can be dropped straight onto its pivot with no offset, and
 * the child joint sits exactly at -length.
 */

/** (radius, y) pairs, bottom first. */
type Profile = Array<[number, number]>;

const lathe = (profile: Profile, segments: number, phiStart = 0, phiLength = Math.PI * 2) =>
  new LatheGeometry(
    profile.map(([r, y]) => new Vector2(Math.max(0.0005, r), y)),
    segments,
    phiStart,
    phiLength,
  );

/**
 * A limb: thick at the joint it hangs from, tapering toward the next one, with
 * a swell where the muscle is. The swell is what stops a tapered cone from
 * reading as a table leg -- and *where* it sits is what separates a calf from
 * a thigh, so it is a parameter and not a constant. A calf is widest just
 * under the knee; a thigh just under the hip; a forearm just under the elbow.
 */
const limb = (
  length: number,
  top: number,
  belly: number,
  end: number,
  bellyAt: number,
): Profile => [
  [end, -length],
  [end * 1.18, -length * 0.9],
  [belly, -length * bellyAt],
  [top * 0.97, -length * 0.08],
  [top, 0],
];

export interface Body {
  torso: BufferGeometry;
  head: BufferGeometry;
  hair: BufferGeometry;
  fringe: BufferGeometry;
  upperArm: BufferGeometry;
  forearm: BufferGeometry;
  thigh: BufferGeometry;
  shin: BufferGeometry;
  foot: BufferGeometry;
  palm: BufferGeometry;
  finger: BufferGeometry;
  joint: BufferGeometry;
  smallJoint: BufferGeometry;
  tinyJoint: BufferGeometry;
  dispose: () => void;
}

export function buildBody(segments: number, rig: {
  chestY: number;
  neckY: number;
  shoulderY: number;
  upperArm: number;
  forearm: number;
  thigh: number;
  shin: number;
}): Body {
  const ring = Math.max(8, segments);

  /*
   * The trunk, in one piece from the pelvis to the base of the skull.
   *
   * Read from the bottom: hips, then a waist that pulls in, then a chest that
   * opens back out to carry the shoulders, then the run into the neck. Those
   * four changes of width are the entire difference between a figure and a
   * cylinder, and they are why this is a lathe and not a capsule.
   */
  const torso = lathe(
    [
      [0.082, -0.075],
      [0.096, -0.03],
      [0.099, 0.0],
      [0.082, 0.075],
      [0.081, 0.115],
      [0.104, 0.185],
      [0.122, 0.25],
      [0.134, rig.chestY],
      [0.145, rig.shoulderY],
      [0.116, rig.shoulderY + 0.035],
      [0.058, rig.neckY - 0.015],
      [0.035, rig.neckY + 0.02],
      [0.032, rig.neckY + 0.06],
    ],
    ring,
  );

  /*
   * The head, with a jaw. A sphere has no chin, and a chin is most of what
   * makes a head point in a direction.
   */
  const head = lathe(
    [
      [0.013, -0.1],
      [0.044, -0.085],
      [0.069, -0.054],
      [0.081, -0.011],
      [0.085, 0.026],
      [0.077, 0.067],
      [0.048, 0.092],
      [0.011, 0.104],
    ],
    ring,
  );

  /*
   * Hair, and it earns its place: in a silhouette this small, hair is the
   * single strongest signal that what you are looking at is a person. A shell
   * over the skull, falling well past the shoulders.
   *
   * Revolved with a gap at the front rather than all the way round, so it
   * frames the face instead of sealing it in. The gap is centred on +Z because
   * that is the direction the figure faces.
   */
  const FRONT_GAP = 1.42;
  const hair = lathe(
    [
      [0.046, -0.42],
      [0.072, -0.31],
      [0.089, -0.19],
      [0.098, -0.075],
      [0.101, 0.0],
      [0.097, 0.048],
      [0.083, 0.082],
      [0.046, 0.106],
      [0.009, 0.118],
    ],
    ring,
    FRONT_GAP / 2,
    Math.PI * 2 - FRONT_GAP,
  );

  /* And a fringe across the brow, so the front of the skull is not bare. */
  const fringe = lathe(
    [
      [0.092, 0.004],
      [0.095, 0.039],
      [0.088, 0.071],
      [0.051, 0.098],
      [0.011, 0.114],
    ],
    ring,
    -FRONT_GAP / 2 - 0.12,
    FRONT_GAP + 0.24,
  );

  /* Deltoid to elbow, elbow to wrist, hip to knee, knee to ankle. */
  const upperArm = lathe(limb(rig.upperArm, 0.052, 0.043, 0.031, 0.4), ring);
  const forearm = lathe(limb(rig.forearm, 0.038, 0.036, 0.021, 0.25), ring);
  const thigh = lathe(limb(rig.thigh, 0.078, 0.07, 0.041, 0.22), ring);
  const shin = lathe(limb(rig.shin, 0.049, 0.05, 0.023, 0.28), ring);

  /* A foot, so the legs stop somewhere instead of just ending. */
  const foot = new BoxGeometry(0.05, 0.028, 0.115);
  foot.translate(0, -0.014, 0.032);

  const palm = new BoxGeometry(0.052, 0.062, 0.024);
  palm.translate(0, -0.031, 0);
  /* Fingers, shared: one geometry, placed four times per hand. */
  const finger = new CapsuleGeometry(0.0085, 0.036, 2, Math.max(5, ring >> 1));

  /*
   * Three sizes, because one was wrong everywhere. At 0.045 the shoulder read
   * as a pauldron and the knee as a swelling; the joint only has to be wide
   * enough to bridge the gap the limb leaves when it swings.
   */
  const joint = new SphereGeometry(0.037, ring, Math.max(4, ring >> 1));
  const smallJoint = new SphereGeometry(0.028, ring, Math.max(4, ring >> 1));
  const tinyJoint = new SphereGeometry(0.022, ring, Math.max(4, ring >> 1));

  const all = [
    torso, head, hair, fringe, upperArm, forearm, thigh, shin,
    foot, palm, finger, joint, smallJoint, tinyJoint,
  ];

  return {
    torso, head, hair, fringe, upperArm, forearm, thigh, shin,
    foot, palm, finger, joint, smallJoint, tinyJoint,
    dispose: () => all.forEach((g) => g.dispose()),
  };
}

/**
 * Where the fingers sit on a hand, and how far each one is curled.
 *
 * Two poses, not one. A hand that points needs an extended index; a hand at
 * rest needs every finger softly closed. Both are static once built, so they
 * are laid out here as data and the figure simply swaps which set it draws --
 * the arm's own movement covers the change.
 */
export interface FingerPlace {
  x: number;
  /** Curl in radians about the hand's X axis. 0 is straight down. */
  curl: number;
  /** Length scale, so the little finger is not the same as the middle one. */
  scale: number;
}

const SPREAD = [-0.019, -0.006, 0.007, 0.019];
const LENGTH = [0.92, 1.0, 0.95, 0.8];

export const HAND_RELAXED: FingerPlace[] = SPREAD.map((x, i) => ({
  x,
  curl: -0.85 - i * 0.06,
  scale: LENGTH[i]!,
}));

export const HAND_POINTING: FingerPlace[] = SPREAD.map((x, i) => ({
  x,
  // The index runs straight on down the arm's axis; the rest fold away.
  curl: i === 0 ? -0.04 : -1.35 - i * 0.05,
  scale: i === 0 ? 1.25 : LENGTH[i]!,
}));
