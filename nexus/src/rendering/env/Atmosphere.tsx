'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { BackSide, Color, type ShaderMaterial } from 'three';
import { ATMOSPHERE_FRAG, ATMOSPHERE_VERT } from '@/shaders/atmosphere';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';

/**
 * The enclosing volume. Inward-facing sphere, no depth write, rendered first.
 * This is the only thing standing between the viewer and the void, and it is
 * doing all the work of implying a room without a single wall.
 */
export function Atmosphere({ density = 0.85 }: { density?: number }) {
  const material = useRef<ShaderMaterial>(null);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uDeep: { value: new Color(PALETTE.void) },
      uMid: { value: new Color(PALETTE.abyss) },
      uGlow: { value: new Color(PALETTE.core) },
      uDensity: { value: density },
      uFreeze: { value: 0 },
      uHorizon: { value: 1 },
    }),
    [density],
  );

  useFrame(() => {
    const material_ = material.current;
    if (!material_) return;
    // Read through the live material: the uniforms object handed to the prop
    // is not the one the renderer uses.
    const u = material_.uniforms;
    u.uTime.value = interaction.sceneTime;
    u.uFreeze.value = interaction.freezeBlend;

    // The world is whatever the environment driver has interpolated to.
    const e = envRuntime;
    (u.uDeep.value as Color).copy(e.deep);
    (u.uMid.value as Color).copy(e.mid);
    (u.uGlow.value as Color).copy(e.glow);
    u.uDensity.value = e.density;
    u.uHorizon.value = e.horizon;
  });

  return (
    <mesh renderOrder={-1000} frustumCulled={false}>
      <sphereGeometry args={[60, 48, 32]} />
      <shaderMaterial
        ref={material}
        vertexShader={ATMOSPHERE_VERT}
        fragmentShader={ATMOSPHERE_FRAG}
        uniforms={uniforms}
        side={BackSide}
        depthWrite={false}
        depthTest={false}
        toneMapped={false}
      />
    </mesh>
  );
}
