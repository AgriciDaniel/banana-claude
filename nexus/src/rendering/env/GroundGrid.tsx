'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Color, DoubleSide, type Mesh, type ShaderMaterial } from 'three';
import { GRID_FRAG, GRID_VERT } from '@/shaders/atmosphere';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';

/**
 * Implied ground. A single large plane carrying an analytically antialiased
 * grid that dissolves into the fog long before its edge, so the viewer reads
 * "floor" without ever being shown where it stops.
 */
export function GroundGrid({ y = -3.1, extent = 52 }: { y?: number; extent?: number }) {
  const material = useRef<ShaderMaterial>(null);
  const mesh = useRef<Mesh>(null);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uColor: { value: new Color(PALETTE.signal) },
      uSpacing: { value: 0.85 },
      uFade: { value: extent * 0.5 },
      uFreeze: { value: 0 },
      uStrength: { value: 1 },
    }),
    [extent],
  );

  useFrame(() => {
    const mat = material.current;
    if (!mat) return;
    const u = mat.uniforms;
    u.uTime.value = interaction.sceneTime;
    u.uFreeze.value = interaction.freezeBlend;

    const e = envRuntime;
    (u.uColor.value as Color).copy(e.grid);
    u.uSpacing.value = e.gridSpacing;
    u.uStrength.value = e.gridStrength;
    if (mesh.current) mesh.current.position.y = e.floorY;
  });

  return (
    <mesh ref={mesh} rotation={[-Math.PI / 2, 0, 0]} position={[0, y, 0]} renderOrder={-500}>
      <planeGeometry args={[extent, extent, 1, 1]} />
      <shaderMaterial
        ref={material}
        vertexShader={GRID_VERT}
        fragmentShader={GRID_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        side={DoubleSide}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}
