/**
 * What the figure is doing, in numbers.
 *
 * A body posed by springs and quaternions has no useful failure mode: when it
 * is wrong it is simply not where you expected, and a screenshot cannot tell
 * you whether it is invisible, behind you, or a hundred units up. This is the
 * readout that can - written every frame by the figure, surfaced on the dev
 * bridge, and the only way the placement constants were ever tuned.
 *
 * Plain mutable object on purpose: it is written at frame rate and must never
 * cause a React render.
 */
export const figureReport = {
  /** 0..1 - how present the body is. Below ~0.004 it stops being drawn. */
  presence: 0,
  /** 0..1 - how committed the pose is to indicating something. */
  showing: 0,
  /** Where the body stands, in world space. */
  x: 0,
  y: 0,
  z: 0,
  /** Where the head projects to, in pixels. Off-screen values are expected
   *  to be negative or beyond the viewport - that is the point of having it. */
  screenX: 0,
  screenY: 0,
  /** How tall the figure comes out on screen, head to foot, in pixels. */
  screenHeight: 0,
  /** 0..1 - how far the mouth is open. It is a level meter, so this is the
   *  number to watch to prove speech is reaching the face at all. */
  mouth: 0,
  /** What it is turned toward: the stage point, or the viewer. */
  looking: 'viewer' as 'viewer' | 'stage',
};
