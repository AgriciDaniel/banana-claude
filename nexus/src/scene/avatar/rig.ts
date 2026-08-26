import { Quaternion, Vector3, type Object3D } from 'three';
import { clamp } from '@/core/math';

/**
 * Proportions, and the two pieces of maths the pose needs.
 *
 * Kept apart from the component because these are the numbers you actually
 * tune -- how long an arm is, how far a head may turn -- and hunting for them
 * inside a hundred lines of JSX is how a rig stops being adjustable.
 *
 * The figure is built around its hips, at local y = 0, facing +Z (toward the
 * viewer's seat). Arms and legs hang along -Y in the rest pose, so every limb
 * is aimed by rotating its own -Y onto a direction, which is one operation
 * instead of three Euler angles that fight each other near the poles.
 */

export const RIG = {
  /**
 * Proportions.
 *
 * About 1.66 units tall and a little over eight heads of it, where the first
 * version was seven and a bit. That single ratio is most of what separates a
 * figure that reads as athletic from one that reads as stocky: the legs carry
 * 55% of the height rather than 52%, the neck is longer, the waist is
 * narrower, and the head is smaller against the shoulders.
 *
 * Eight heads is the classical heroic figure rather than the average one, and
 * that is deliberate -- this thing is meant to look built, not surveyed.
 */
  footY: -0.925,
  kneeY: -0.462,
  chestY: 0.305,
  neckY: 0.482,
  headY: 0.642,
  /** Half-height of the skull, for placing anything that sits on it. */
  headRadius: 0.11,
  /** How far forward the face sits, so the eyes and mouth clear the skull. */
  faceZ: 0.083,

  shoulderY: 0.404,
  shoulderX: 0.152,
  upperArm: 0.328,
  forearm: 0.302,

  hipX: 0.067,
  thigh: 0.462,
  shin: 0.438,

  limbRadius: 0.037,
  armRadius: 0.031,
} as const;

/** Every limb hangs this way before anything aims it. */
export const REST_DIR = new Vector3(0, -1, 0);
/** The head's own forward. */
export const FORWARD = new Vector3(0, 0, 1);

/** How far the head may turn off its shoulders, in radians. */
export const HEAD_CONE = 0.92;

const tmpFrom = new Vector3();
const tmpDir = new Vector3();
const tmpQuat = new Quaternion();

/**
 * Aim a joint's rest axis at a point in the world.
 *
 * The target arrives in world space -- it is a panel standing in the room --
 * while the joint turns in its parent's space, so the direction is carried
 * back through the parent's rotation before the swing is built. Skipping that
 * is what makes a rigged arm point correctly only while its owner faces due
 * north.
 *
 * `out` receives the swing; the caller decides how fast to move onto it,
 * because how quickly a limb reaches its target is characterisation, not
 * geometry.
 */
export function aimAt(joint: Object3D, target: Vector3, axis: Vector3, out: Quaternion): void {
  joint.getWorldPosition(tmpFrom);
  tmpDir.copy(target).sub(tmpFrom);
  if (tmpDir.lengthSq() < 1e-8) {
    out.identity();
    return;
  }
  tmpDir.normalize();

  const parent = joint.parent;
  if (parent) {
    parent.getWorldQuaternion(tmpQuat).invert();
    tmpDir.applyQuaternion(tmpQuat);
  }

  out.setFromUnitVectors(axis, tmpDir);
}

/**
 * Pull a direction back inside a cone around `axis`.
 *
 * A head that can turn any amount stops reading as a head the first time it
 * looks over its own shoulder. Interpolating toward the axis and renormalising
 * is not an exact angular clamp, but inside a cone of this size the error is
 * under a degree and it costs one lerp instead of an axis-angle rebuild.
 */
export function clampToCone(dir: Vector3, axis: Vector3, maxAngle: number): void {
  const angle = Math.acos(clamp(dir.dot(axis), -1, 1));
  if (angle <= maxAngle) return;
  dir.lerp(axis, 1 - maxAngle / angle).normalize();
}

/**
 * Capsule arguments for a bone of a given total length.
 *
 * Three's capsule adds a hemisphere at each end on top of the length it is
 * given, so a bone asked for 0.30 comes out at 0.30 plus two radii and every
 * joint ends up slightly further down the limb than the rig says.
 */
export function boneArgs(length: number, radius: number, segments: number): [number, number, number, number] {
  const straight = Math.max(0.01, length - radius * 2);
  return [radius, straight, Math.max(2, segments >> 1), segments];
}
