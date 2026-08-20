'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { Group } from 'three';
import { SPACE } from '@/config/theme';
import { useMediaStore } from '@/stores/useMediaStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { MediaFrame, frameSize } from './MediaFrame';
import type { MediaItem } from '@/media/types';

/**
 * Where content stands in the room.
 *
 * Centre stage when nothing else is open, and stepped aside when a module
 * expands, so an image and a detail panel never fight for the same space. The
 * move is a spring, so opening a module pushes the picture out of the way
 * rather than teleporting it.
 */
/**
 * The assistant's particle text holds a band around y = 1.9 and stays there
 * between replies, so the frame sits low enough that its top edge passes
 * beneath the last line instead of being read through it.
 */
const STAGE_Y = 0.5;

/**
 * Where each panel sits when an answer is told in several.
 *
 * Stacking was right when a second panel replaced the first, and wrong the
 * moment they became complementary: a photograph, the factsheet that explains
 * it and the radar that measures it are one answer in three pieces, and an
 * opaque panel in front of the other two buries the answer it belongs to.
 *
 * Everything from the current question therefore stands in a row. Each place
 * is measured from the panels' own widths, so a tall portrait beside two wide
 * charts still comes out evenly spaced, and the row shrinks as a whole until
 * it fits rather than letting any one panel run off the side.
 */
/*
 * Measured against what the camera actually shows at the stage's distance,
 * not guessed from the panel widths: the first estimate ran a three-panel row
 * off both edges of the screen.
 */
const ROW_WIDTH = 4.2;
const ROW_GAP = 0.16;

function rowPlaces(stack: MediaItem[]): Array<{ x: number; scale: number }> | null {
  if (stack.length < 2) return null;

  /*
   * The stack is newest first; a row laid out in that order reads backwards.
   * Reversed here so panels appear left to right in the order they arrived,
   * which is the order they were meant to be read in -- the photograph, then
   * what it is, then what it measures.
   */
  const ordered = [...stack].reverse();
  const sizes = ordered.map((item) => frameSize(item).width);
  const total = sizes.reduce((sum, w) => sum + w, 0) + ROW_GAP * (stack.length - 1);
  const scale = Math.min(1, ROW_WIDTH / total);

  // Laid out left to right in the order they arrived, which is the order they
  // were meant to be read in.
  let cursor = -(total * scale) / 2;
  const placed = sizes.map((width) => {
    const w = width * scale;
    const x = cursor + w / 2;
    cursor += w + ROW_GAP * scale;
    return { x, scale };
  });
  // Handed back in stack order, so the caller can index by it directly.
  return placed.reverse();
}

export function MediaStage() {
  const group = useRef<Group>(null);
  const stack = useMediaStore((s) => s.stack);
  const retiring = useMediaStore((s) => s.retiring);
  const places = useMemo(() => rowPlaces(stack), [stack]);
  const expandedId = useCarouselStore((s) => s.expandedId);

  const motion = useMemo(
    () => new Spring3([0, STAGE_Y, SPACE.orbitRadius + 2.1], SPRINGS.glide),
    [],
  );
  /*
   * Stepping aside is not enough on its own: at full size a landscape frame
   * pushed left runs off the edge of the screen, which is exactly what happens
   * when a post is opened from the module panel that caused the step.
   */
  const shrink = useMemo(() => new Spring(1, SPRINGS.glide), []);

  useFrame((_, delta) => {
    if (!group.current) return;
    const dt = delta > 0.05 ? 0.05 : delta;

    /*
     * Aside while a module holds the centre -- but only just. The module panel
     * opens on the right, so the content steps left; step it any further and a
     * chart ends up behind the telemetry panel in the corner, which is the one
     * moment the user most wants to read it. The yaw is gentle for the same
     * reason: a photograph survives being turned away, a column of figures
     * does not.
     */
    motion.set(
      expandedId ? -2.1 : 0,
      expandedId ? 0.45 : STAGE_Y,
      SPACE.orbitRadius + (expandedId ? 1.7 : 2.1),
    );
    motion.update(dt);
    shrink.set(expandedId ? 0.78 : 1);
    shrink.update(dt);

    group.current.position.set(motion.x.value, motion.y.value, motion.z.value);
    group.current.scale.setScalar(shrink.value);
    group.current.rotation.y = expandedId ? 0.2 : 0;
    group.current.visible = stack.length + retiring.length > 0;
  });

  if (stack.length === 0 && retiring.length === 0) return null;

  return (
    <group ref={group} name="media-stage">
      {stack.map((item, index) => (
        <MediaFrame key={item.id} item={item} index={index} row={places?.[index] ?? null} />
      ))}

      {/* On their way out: behind everything, shrinking, not interactive. */}
      {retiring.map((item, index) => (
        <MediaFrame key={item.id} item={item} index={stack.length + index} retiring />
      ))}
    </group>
  );
}
