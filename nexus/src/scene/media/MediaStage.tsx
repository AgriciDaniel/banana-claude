'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { Group } from 'three';
import { SPACE } from '@/config/theme';
import { useMediaStore } from '@/stores/useMediaStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { MediaFrame } from './MediaFrame';
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
 * Where a frame sits when two belong together.
 *
 * A photograph and the factsheet that explains it are one answer in two
 * pieces, and stacking them buried the picture completely behind an opaque
 * panel. When the current topic holds exactly a visual and a chart, they stand
 * side by side instead -- picture on the left, reading matter on the right,
 * which is the order they are looked at in.
 */
function pairSide(stack: MediaItem[], index: number): 'left' | 'right' | null {
  if (stack.length !== 2) return null;
  const kinds = stack.map((m) => m.kind);
  const visual = kinds.findIndex((k) => k === 'image' || k === 'video');
  const chart = kinds.findIndex((k) => k === 'chart');
  if (visual === -1 || chart === -1) return null;
  return index === visual ? 'left' : 'right';
}

export function MediaStage() {
  const group = useRef<Group>(null);
  const stack = useMediaStore((s) => s.stack);
  const retiring = useMediaStore((s) => s.retiring);
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
        <MediaFrame key={item.id} item={item} index={index} pairSide={pairSide(stack, index)} />
      ))}

      {/* On their way out: behind everything, shrinking, not interactive. */}
      {retiring.map((item, index) => (
        <MediaFrame key={item.id} item={item} index={stack.length + index} retiring />
      ))}
    </group>
  );
}
