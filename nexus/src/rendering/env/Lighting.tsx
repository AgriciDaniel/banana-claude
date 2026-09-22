'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import type { AmbientLight, PointLight, SpotLight } from 'three';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';

/**
 * Scene lighting.
 *
 * Three sources, no more: a cold key from above-left, a deep blue fill from
 * behind-right, and a rim that tracks the user's hand. Industrial minimalism
 * applies to the lighting rig too - every extra light is a decision you now
 * have to defend in every state of the UI.
 */
export function Lighting() {
  const key = useRef<SpotLight>(null);
  const hand = useRef<PointLight>(null);
  const ambient = useRef<AmbientLight>(null);
  const fill = useRef<PointLight>(null);

  useFrame((_, delta) => {
    const t = interaction.sceneTime;
    const e = envRuntime;

    // The rig itself is environment-driven; only the hand light is not.
    if (ambient.current) {
      ambient.current.intensity = e.ambient;
      ambient.current.color.copy(e.mid);
    }
    if (key.current) {
      key.current.intensity = e.keyIntensity;
      key.current.color.copy(e.keyColor);
    }
    if (fill.current) {
      fill.current.intensity = e.fillIntensity;
      fill.current.color.copy(e.fillColor);
    }

    if (key.current) {
      // Barely-there sway, enough to keep speculars from looking painted on.
      key.current.position.x = -5.5 + Math.sin(t * 0.07) * 0.7;
      key.current.position.z = 3.2 + Math.cos(t * 0.05) * 0.6;
    }

    if (hand.current) {
      // The hand light chases the reticle with a soft lag.
      const k = 1 - Math.exp(-6 * delta);
      hand.current.position.x += (interaction.aimX - hand.current.position.x) * k;
      hand.current.position.y += (interaction.aimY - hand.current.position.y) * k;
      hand.current.position.z += (interaction.aimZ + 0.8 - hand.current.position.z) * k;
      const target = interaction.grabbedId ? 5.5 : 2.2;
      hand.current.intensity += (target - hand.current.intensity) * k;
    }
  });

  return (
    <>
      {/* Ambient is intentionally almost nothing: the glass must earn its light. */}
      <ambientLight ref={ambient} intensity={0.18} color={PALETTE.abyss} />

      <hemisphereLight args={[PALETTE.signal, PALETTE.void, 0.35]} />

      <spotLight
        ref={key}
        position={[-5.5, 7.5, 3.2]}
        angle={0.9}
        penumbra={1}
        distance={30}
        intensity={90}
        color={PALETTE.lumen}
      />

      <pointLight
        ref={fill}
        position={[6.5, 1.5, -6]}
        intensity={38}
        distance={26}
        color={PALETTE.core}
      />

      {/* Warm accent, far below threshold - it only shows on warning states. */}
      <pointLight position={[0, -3.4, 2]} intensity={6} distance={12} color={PALETTE.ember} />

      <pointLight ref={hand} intensity={0} distance={7} decay={2} color={PALETTE.signal} />
    </>
  );
}
