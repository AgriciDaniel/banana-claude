'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Trail } from '@react-three/drei';
import { animated, useSpring } from '@react-spring/three';
import { AdditiveBlending, DoubleSide, type Group, type Mesh } from 'three';
import { PALETTE } from '@/config/theme';
import { gestureSnapshot, interaction } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { useCarouselStore } from '@/stores/useCarouselStore';

/**
 * The reticle.
 *
 * The user's hand made visible in the scene. It is a cursor in the sense that
 * it shows where you are pointing, and an instrument in the sense that its
 * shape reports what the system currently believes your hand is doing —
 * open ring for an open hand, contracted core for a pinch, warm ring when the
 * world is frozen.
 *
 * The scale/opacity transitions run on react-spring rather than the scene's own
 * integrator on purpose: this is a UI affordance, not a physical object, and it
 * should feel responsive rather than massive.
 */
export function HandReticle() {
  const group = useRef<Group>(null);
  const core = useRef<Mesh>(null);
  const tracking = useSystemStore((s) => s.tracking);
  const input = useSystemStore((s) => s.input);
  const dragging = useCarouselStore((s) => s.draggingId !== null);

  const visible = input !== 'none' && (input !== 'hand' || tracking === 'active');

  const [{ scale, opacity }] = useSpring(
    () => ({
      scale: dragging ? 0.62 : 1,
      opacity: visible ? 1 : 0,
      config: { tension: 320, friction: 22, mass: 0.8 },
    }),
    [dragging, visible],
  );

  useFrame((_, delta) => {
    if (!group.current) return;
    group.current.position.set(interaction.aimX, interaction.aimY, interaction.aimZ);
    // Always square to the viewer.
    group.current.lookAt(0, interaction.aimY, 40);

    const pinch = gestureSnapshot.primary?.pinch ?? (dragging ? 1 : 0);
    if (core.current) {
      const s = 1 - pinch * 0.55;
      core.current.scale.setScalar(s);
      core.current.rotation.z += delta * (0.4 + pinch * 3.2);
    }
  });

  const color = interaction.frozen ? PALETTE.ember : dragging ? PALETTE.lock : PALETTE.signal;

  return (
    <group ref={group} visible={visible}>
      <animated.group scale={scale}>
        {/* Outer ring — the aim. */}
        <mesh>
          <ringGeometry args={[0.075, 0.088, 48]} />
          <animated.meshBasicMaterial
            color={color}
            transparent
            opacity={opacity}
            blending={AdditiveBlending}
            depthWrite={false}
            side={DoubleSide}
            toneMapped={false}
          />
        </mesh>

        {/* Rotating bracket — the posture readout. */}
        <mesh ref={core}>
          <ringGeometry args={[0.03, 0.042, 4, 1, 0, Math.PI * 1.55]} />
          <animated.meshBasicMaterial
            color={PALETTE.lumen}
            transparent
            opacity={opacity}
            blending={AdditiveBlending}
            depthWrite={false}
            side={DoubleSide}
            toneMapped={false}
          />
        </mesh>

        {/* Core dot, trailed so fast motion leaves a light streak. */}
        <Trail width={0.7} length={4} color={color} attenuation={(t) => t * t} decay={2.4}>
          <mesh>
            <sphereGeometry args={[0.012, 12, 12]} />
            <meshBasicMaterial color={PALETTE.lumen} toneMapped={false} />
          </mesh>
        </Trail>
      </animated.group>
    </group>
  );
}
