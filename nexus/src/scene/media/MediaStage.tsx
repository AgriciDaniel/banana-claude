'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { Group } from 'three';
import { SPACE } from '@/config/theme';
import { useMediaStore } from '@/stores/useMediaStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { MediaFrame } from './MediaFrame';

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

export function MediaStage() {
  const group = useRef<Group>(null);
  const stack = useMediaStore((s) => s.stack);
  const expandedId = useCarouselStore((s) => s.expandedId);

  const motion = useMemo(
    () => new Spring3([0, STAGE_Y, SPACE.orbitRadius + 2.1], SPRINGS.glide),
    [],
  );

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

    group.current.position.set(motion.x.value, motion.y.value, motion.z.value);
    group.current.rotation.y = expandedId ? 0.2 : 0;
    group.current.visible = stack.length > 0;
  });

  if (stack.length === 0) return null;

  return (
    <group ref={group} name="media-stage">
      {stack.map((item, index) => (
        <MediaFrame key={item.id} item={item} index={index} />
      ))}
    </group>
  );
}
