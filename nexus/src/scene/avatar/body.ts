import {
  BoxGeometry,
  CapsuleGeometry,
  CatmullRomCurve3,
  CylinderGeometry,
  LatheGeometry,
  SphereGeometry,
  TorusGeometry,
  TubeGeometry,
  Vector2,
  Vector3,
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

/**
 * The skull.
 *
 * Shared, because the helmet is not one object: it is a shell with a face
 * plate recessed into it, a jaw plate under that and a crown over the back,
 * and every one of those has to be cut from the same curve or they will not
 * sit flush against each other.
 */
const HEAD_PROFILE: Profile = [
  [0.013, -0.1],
  [0.044, -0.085],
  [0.069, -0.054],
  [0.081, -0.011],
  [0.085, 0.026],
  [0.077, 0.067],
  [0.048, 0.092],
  [0.011, 0.104],
];

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
  const head = lathe(HEAD_PROFILE, ring);

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
  const upperArm = lathe(limb(rig.upperArm, 0.047, 0.039, 0.028, 0.4), ring);
  const forearm = lathe(limb(rig.forearm, 0.034, 0.032, 0.019, 0.25), ring);
  const thigh = lathe(limb(rig.thigh, 0.07, 0.062, 0.036, 0.22), ring);
  const shin = lathe(limb(rig.shin, 0.044, 0.046, 0.02, 0.28), ring);

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

/**
 * The mechanism under the shell.
 *
 * A plated machine is not a smooth body with lines drawn on it. It is a dark
 * frame -- carbon, cable, actuator -- with white plates laid over the top, and
 * every reference shows exactly where the plates stop: the neck, the flanks,
 * the backs of the joints. That gap is the detail. Drawing seams on an unbroken
 * surface can only ever suggest it.
 *
 * So the trunk is built the other way round from here on. The lathe that used
 * to BE the torso becomes the core, and the white shell goes on over it as
 * separate sectors that leave the core showing between them.
 */

/**
 * A sector of a revolved profile, swollen outward.
 *
 * `swell` lifts every radius so the piece sits proud of whatever it covers --
 * which is what makes it read as a plate laid on top rather than as a stripe
 * painted on.
 */
function sector(
  profile: Profile,
  segments: number,
  centre: number,
  span: number,
  swell: number,
): BufferGeometry {
  return lathe(
    profile.map(([r, y]) => [r + swell, y] as [number, number]),
    segments,
    centre - span / 2,
    span,
  );
}

/** The trunk profile, so plates and core can be cut from the same curve. */
function trunkProfile(rig: { chestY: number; neckY: number; shoulderY: number }): Profile {
  return [
    [0.074, -0.078],
    [0.088, -0.032],
    [0.091, 0.0],
    [0.073, 0.078],
    [0.071, 0.12],
    [0.098, 0.192],
    [0.12, 0.256],
    [0.135, rig.chestY],
    [0.149, rig.shoulderY],
    [0.118, rig.shoulderY + 0.038],
    [0.055, rig.neckY - 0.02],
    [0.032, rig.neckY + 0.02],
    [0.03, rig.neckY + 0.062],
  ];
}

/** Cut a profile down to a height range, keeping the curve's own shape. */
function slice(profile: Profile, from: number, to: number): Profile {
  const at = (y: number): number => {
    for (let i = 1; i < profile.length; i++) {
      const [r0, y0] = profile[i - 1]!;
      const [r1, y1] = profile[i]!;
      if (y >= y0 && y <= y1) {
        const t = y1 === y0 ? 0 : (y - y0) / (y1 - y0);
        return r0 + (r1 - r0) * t;
      }
    }
    return profile[profile.length - 1]![0];
  };
  const inner = profile.filter(([, y]) => y > from && y < to);
  return [[at(from), from], ...inner, [at(to), to]];
}

export interface Mechanism {
  /** The dark frame the plates are laid over. */
  core: BufferGeometry;
  /** Chest, abdomen and back: white shell, front and rear sectors. */
  chestPlate: BufferGeometry;
  backPlate: BufferGeometry;
  abBand: BufferGeometry;
  /** Cables running from the base of the skull into the shoulders. */
  cable: BufferGeometry;
  /** The circular units at the shoulder and the hip. */
  disc: BufferGeometry;
  collar: BufferGeometry;
  discRing: BufferGeometry;
  /** A lit slot, for the light let into a plate. */
  slot: BufferGeometry;
  /*
   * The helmet, in pieces. The references carry no face at all: a smooth
   * cranial shell, a dark plate where a face would be, a jaw under it, a crown
   * over the back, and a large circular unit at the temple. Building it this
   * way rather than hanging a picture on the front is the only way the detail
   * belongs to the head instead of floating in front of it.
   */
  facePlate: BufferGeometry;
  jawPlate: BufferGeometry;
  crownPlate: BufferGeometry;
  templeRing: BufferGeometry;
  templeCore: BufferGeometry;
  /** Finger bones, three to a finger, and the knuckle between them. */
  phalanx: BufferGeometry;
  knuckle: BufferGeometry;
  /*
   * Pistons. A joint that only bends is a hinge; a joint with an actuator
   * across it is a machine, and it is the single cheapest thing that reads as
   * engineering rather than as moulding.
   */
  pistonBody: BufferGeometry;
  pistonRod: BufferGeometry;
  /** The lights let into the knuckles of the exposed hand. */
  led: BufferGeometry;
  dispose: () => void;
}

export function buildMechanism(
  segments: number,
  rig: { chestY: number; neckY: number; shoulderY: number },
): Mechanism {
  const ring = Math.max(8, segments);
  const trunk = trunkProfile(rig);

  /* The core is the trunk itself, very slightly shrunk so nothing z-fights. */
  const core = lathe(
    trunk.map(([r, y]) => [r - 0.004, y] as [number, number]),
    ring,
  );

  /*
   * Front and back are separate pieces with a gap down each flank. That gap --
   * the dark core showing between two white plates -- is the single detail that
   * makes the difference between armour and a painted cylinder.
   */
  const FRONT = Math.PI / 2;
  const chestPlate = sector(slice(trunk, 0.175, rig.shoulderY + 0.02), ring, FRONT, 2.62, 0.007);
  const backPlate = sector(
    slice(trunk, 0.16, rig.shoulderY + 0.02),
    ring,
    FRONT + Math.PI,
    2.1,
    0.007,
  );
  /* One band; the figure stacks three of them down the abdomen. */
  const abBand = sector(slice(trunk, 0.0, 0.04), ring, FRONT, 2.62, 0.006);

  /*
   * Neck cables. Built once along a curve and placed four times -- the
   * references run a bundle of them from the base of the skull down behind the
   * collar, and a bundle is the point: one cable reads as a mistake.
   */
  /*
   * Routed around the SIDE of the neck, not behind it. The first pass ran them
   * down the back, which is where they belong on a real machine and where the
   * viewer, who is standing in front, cannot see a single one of them.
   */
  const cable = new TubeGeometry(
    new CatmullRomCurve3([
      new Vector3(0.026, rig.neckY + 0.058, -0.006),
      new Vector3(0.05, rig.neckY - 0.005, -0.014),
      new Vector3(0.062, rig.shoulderY - 0.01, -0.004),
      new Vector3(0.055, rig.chestY - 0.015, 0.02),
    ]),
    14,
    0.0068,
    Math.max(5, ring >> 1),
    false,
  );

  /*
   * Recessed, not raised: the face is the one plate that sits BELOW the shell
   * around it, which is what gives the brow and the cheekbones an edge to
   * catch light on.
   */
  const facePlate = sector(slice(HEAD_PROFILE, -0.088, 0.055), ring, FRONT, 1.62, -0.007);
  const jawPlate = sector(slice(HEAD_PROFILE, -0.101, -0.042), ring, FRONT, 1.95, 0.004);
  const crownPlate = sector(
    slice(HEAD_PROFILE, 0.012, 0.101),
    ring,
    FRONT + Math.PI,
    4.3,
    0.004,
  );
  const templeRing = new TorusGeometry(0.03, 0.0075, 8, ring);
  const templeCore = new CylinderGeometry(0.024, 0.024, 0.012, ring);

  const disc = new CylinderGeometry(0.042, 0.042, 0.02, ring);
  /* The collar the cables gather into, at the base of the skull. */
  const collar = new CylinderGeometry(0.046, 0.052, 0.026, ring);
  const discRing = new TorusGeometry(0.03, 0.005, 6, ring);
  const slot = new BoxGeometry(0.03, 0.008, 0.006);

  const pistonBody = new CylinderGeometry(0.0105, 0.0105, 0.042, Math.max(6, ring >> 1));
  const pistonRod = new CylinderGeometry(0.0046, 0.0046, 0.05, Math.max(5, ring >> 1));
  const led = new SphereGeometry(0.0056, Math.max(5, ring >> 2), Math.max(4, ring >> 2));

  const phalanx = new CapsuleGeometry(0.008, 0.014, 2, Math.max(5, ring >> 1));
  const knuckle = new SphereGeometry(0.0092, Math.max(6, ring >> 1), Math.max(4, ring >> 2));

  const all = [
    core, chestPlate, backPlate, abBand, cable, disc, collar, discRing, slot, phalanx, knuckle,
    facePlate, jawPlate, crownPlate, templeRing, templeCore, pistonBody, pistonRod, led,
  ];
  return {
    core, chestPlate, backPlate, abBand, cable, disc, collar, discRing, slot, phalanx, knuckle,
    facePlate, jawPlate, crownPlate, templeRing, templeCore, pistonBody, pistonRod, led,
    dispose: () => all.forEach((g) => g.dispose()),
  };
}
