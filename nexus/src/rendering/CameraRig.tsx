'use client';

import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import gsap from 'gsap';
import { Vector3 } from 'three';
import { SPACE } from '@/config/theme';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { interaction } from '@/stores/runtime';
import { noise1 } from '@/core/math';
import { bus } from '@/stores/bus';
import { envRuntime } from '@/stores/useEnvironmentStore';

/**
 * Camera.
 *
 * The viewer is never still. Two motions are layered:
 *
 *   - a continuous low-frequency drift on incommensurate periods, which is
 *     what makes the space feel occupied rather than photographed;
 *   - GSAP-tweened seat changes when a card expands, because a deliberate
 *     framing change should read as *authored*, not as another spring.
 *
 * Drift is always additive on top of the tween target, so the two never fight.
 */

const base = new Vector3(...SPACE.cameraStart);
const lookTarget = new Vector3(0, 0, 0);

export function CameraRig() {
  const camera = useThree((s) => s.camera);
  const expandedId = useCarouselStore((s) => s.expandedId);
  const reduced = useSystemStore((s) => s.capabilities?.prefersReducedMotion ?? false);

  /** Tweened by GSAP; drift is applied on top of this every frame. */
  const seat = useRef({ x: SPACE.cameraStart[0], y: SPACE.cameraStart[1], z: SPACE.cameraStart[2], look: 0 });
  /** Choreographed roll and push, layered on top of the seat. */
  const shot = useRef({ roll: 0, push: 0 });

  useEffect(() => {
    const target = expandedId
      ? { x: 0, y: SPACE.cameraFocus[1], z: SPACE.cameraStart[2] + 0.75, look: 0.18 }
      : { x: SPACE.cameraStart[0], y: SPACE.cameraStart[1], z: SPACE.cameraStart[2], look: 0 };

    const tween = gsap.to(seat.current, {
      ...target,
      duration: expandedId ? 1.15 : 0.9,
      // Slow in, fast middle, long settle - a dolly, not a cut.
      ease: expandedId ? 'power3.inOut' : 'power2.out',
      overwrite: true,
    });
    return () => {
      tween.kill();
    };
  }, [expandedId]);

  /*
   * World changes get a camera move, not just a colour change. A short pull
   * back with a touch of roll reads as the operator leaning away while the
   * room rebuilds itself around them - the single cheapest thing that makes a
   * transition feel directed rather than automatic.
   */
  useEffect(() => {
    return bus.on('env:change', ({ source }) => {
      const strength = source === 'module' ? 1 : 0.65;
      gsap.killTweensOf(shot.current);
      gsap
        .timeline()
        .to(shot.current, {
          push: 1.15 * strength,
          roll: 0.035 * strength,
          duration: 0.75,
          ease: 'power3.out',
        })
        .to(shot.current, {
          push: 0,
          roll: 0,
          duration: 1.5,
          ease: 'power2.inOut',
        });
    });
  }, []);

  useFrame((_, delta) => {
    const t = interaction.sceneTime;
    const amp = reduced ? 0.15 : 1;
    // Freezing stills the camera too, but never completely - a dead-frozen
    // camera reads as a crashed application.
    const live = 1 - interaction.freezeBlend * 0.8;

    const driftX = noise1(t * 0.13, 1) * 0.19 * amp * live;
    const driftY = noise1(t * 0.11, 7) * 0.13 * amp * live + Math.sin(t * 0.21) * 0.03 * amp;
    const driftZ = noise1(t * 0.09, 13) * 0.16 * amp * live;

    // Very slight lean toward whatever the hand is doing.
    const leanX = interaction.aimX * 0.035;
    const leanY = interaction.aimY * 0.025;

    base.set(
      seat.current.x + driftX + leanX,
      seat.current.y + driftY + leanY + shot.current.push * 0.22,
      seat.current.z + driftZ + shot.current.push,
    );

    const k = 1 - Math.exp(-9 * delta);
    camera.position.lerp(base, k);

    lookTarget.set(
      driftX * 0.35 + leanX * 0.5,
      seat.current.look + driftY * 0.3,
      SPACE.orbitRadius * 0.1,
    );
    camera.lookAt(lookTarget);
    // Roll after lookAt, or lookAt would immediately undo it.
    camera.rotateZ(shot.current.roll + envRuntime.morph * 0.006);
    camera.updateMatrixWorld();
  }, -50);

  return null;
}
