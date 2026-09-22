'use client';

import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, DoubleSide, type Mesh, type ShaderMaterial } from 'three';
import { WAKE_FRAG, WAKE_VERT } from '@/shaders/wake';
import { RIPPLE_FRAG, RIPPLE_VERT } from '@/shaders/wake';
import { Color } from 'three';
import { bus } from '@/stores/bus';
import { envRuntime } from '@/stores/useEnvironmentStore';
import { interaction } from '@/stores/runtime';
import { useMemo } from 'react';

/**
 * The moment the world changes.
 *
 * A pressure wave leaves the viewer and passes outward through the room, with
 * a matching ring travelling across the floor. It reuses the wake shaders from
 * Phase 2 rather than inventing a second visual language for the same idea:
 * something has propagated through the space.
 *
 * The colour is taken from the world being ARRIVED AT, so the wave reads as
 * the new environment washing in rather than as a generic flash.
 */

const DURATION = 1.9;
const RADIUS = 30;

export function WorldShift() {
  const shell = useRef<Mesh>(null);
  const floor = useRef<Mesh>(null);
  const progress = useRef(1);

  const shellUniforms = useMemo(
    () => ({
      uColor: { value: new Color('#63C9FF') },
      uProgress: { value: 1 },
      uIntensity: { value: 1.15 },
    }),
    [],
  );

  const floorUniforms = useMemo(
    () => ({
      uColor: { value: new Color('#63C9FF') },
      uProgress: { value: 1 },
      uRadius: { value: RADIUS },
      uIntensity: { value: 1.4 },
    }),
    [],
  );

  useEffect(() => {
    return bus.on('env:change', () => {
      progress.current = 0;
    });
  }, []);

  useFrame((_, delta) => {
    if (progress.current >= 1) {
      if (shell.current) shell.current.visible = false;
      if (floor.current) floor.current.visible = false;
      return;
    }

    progress.current = Math.min(1, progress.current + delta / DURATION);
    const p = progress.current;
    // Decelerating front: fast departure, long dissipation into the fog.
    const eased = 1 - Math.pow(1 - p, 2.6);

    // Tinted by the destination world, picked up live as it interpolates.
    (shellUniforms.uColor.value as Color).copy(envRuntime.glow);
    (floorUniforms.uColor.value as Color).copy(envRuntime.grid);
    shellUniforms.uProgress.value = p;
    floorUniforms.uProgress.value = p;

    if (shell.current) {
      shell.current.visible = true;
      shell.current.scale.setScalar(0.6 + eased * RADIUS);
    }
    if (floor.current) {
      floor.current.visible = true;
      floor.current.position.y = envRuntime.floorY + 0.04;
    }

    void interaction.sceneTime;
  });

  return (
    <group name="world-shift">
      <mesh ref={shell} visible={false} frustumCulled={false} renderOrder={-88}>
        <sphereGeometry args={[1, 44, 30]} />
        <shaderMaterial
          vertexShader={WAKE_VERT}
          fragmentShader={WAKE_FRAG}
          uniforms={shellUniforms}
          transparent
          depthWrite={false}
          depthTest={false}
          side={DoubleSide}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>

      <mesh
        ref={floor}
        visible={false}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -3, 0]}
        renderOrder={-78}
      >
        <planeGeometry args={[RADIUS * 2, RADIUS * 2, 1, 1]} />
        <shaderMaterial
          vertexShader={RIPPLE_VERT}
          fragmentShader={RIPPLE_FRAG}
          uniforms={floorUniforms}
          transparent
          depthWrite={false}
          side={DoubleSide}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}
