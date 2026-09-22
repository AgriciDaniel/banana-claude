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

/**
 * Bring the figure forward to be looked at.
 *
 * Every judgement about this body -- proportions, plating, the helmet, whether
 * a seam reads at all -- was made by editing two constants, reloading, looking,
 * and editing them back. That is a slow way to answer "does this look right",
 * and it leaves the source in a state where forgetting to revert ships a
 * two-metre robot standing in front of the content.
 *
 * So the override lives here instead. `__nexus.inspect()` walks the figure out
 * to the middle of the room at a size you can actually see; `inspect(0)` puts
 * it back. Nothing in the shipped path reads this unless it is switched on.
 */
export const inspect = {
  active: false,
  /*
   * Far enough back that the whole body fits the frame at this size. Measured
   * rather than guessed: at 0.68 scale and z 6.6 the figure lands 410 pixels
   * tall, so twice the size at three quarters the apparent distance comes out
   * near 900 -- which is the viewport, near enough.
   */
  scale: 2.6,
  x: 0,
  y: -0.35,
  z: 5.6,
};
