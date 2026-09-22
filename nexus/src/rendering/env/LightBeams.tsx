'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Color, DoubleSide, type Group, type ShaderMaterial } from 'three';
import { BEAM_FRAG, BEAM_VERT } from '@/shaders/beam';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { hash11 } from '@/core/math';
import { envRuntime } from '@/stores/useEnvironmentStore';

interface BeamSpec {
  position: [number, number, number];
  rotation: [number, number, number];
  radius: number;
  length: number;
  seed: number;
  intensity: number;
  orbit: number;
  orbitSpeed: number;
}

/**
 * Moving shafts of light.
 *
 * Cones rendered additively with a grazing-angle falloff. They orbit the
 * viewer slowly on independent periods, which is what keeps the space feeling
 * inhabited rather than staged - at no point do two beams line up twice.
 */
export function LightBeams({ count = 6 }: { count?: number }) {
  const group = useRef<Group>(null);
  const materials = useRef<ShaderMaterial[]>([]);

  const beams = useMemo<BeamSpec[]>(() => {
    return Array.from({ length: count }, (_, i) => {
      const seed = hash11(i * 3.77 + 1.13);
      const seed2 = hash11(i * 7.31 + 4.9);
      const angle = (i / count) * Math.PI * 2 + seed * 0.9;
      const dist = 5.5 + seed2 * 6;
      return {
        position: [Math.cos(angle) * dist, 4.2 + seed * 2.4, Math.sin(angle) * dist],
        // Tilted off vertical so the shafts rake across the volume.
        rotation: [(seed - 0.5) * 0.5, angle, (seed2 - 0.5) * 0.42],
        radius: 0.9 + seed2 * 1.7,
        length: 9 + seed * 6,
        seed,
        intensity: 0.55 + seed2 * 0.75,
        orbit: angle,
        orbitSpeed: (0.012 + seed * 0.022) * (seed2 > 0.5 ? 1 : -1),
      };
    });
  }, [count]);

  const uniformSets = useMemo(
    () =>
      beams.map((b) => ({
        uTime: { value: 0 },
        uColor: { value: new Color(b.seed > 0.82 ? PALETTE.lumen : PALETTE.signal) },
        uIntensity: { value: b.intensity },
        uSeed: { value: b.seed },
        uFreeze: { value: 0 },
      })),
    [beams],
  );

  useFrame(() => {
    const t = interaction.sceneTime;
    const e = envRuntime;
    for (let i = 0; i < materials.current.length; i++) {
      const mat = materials.current[i];
      if (!mat) continue;
      const u = mat.uniforms;
      u.uTime.value = t;
      u.uFreeze.value = interaction.freezeBlend;
      (u.uColor.value as Color).copy(e.beamColor);
      u.uIntensity.value = (beams[i]?.intensity ?? 1) * e.beamIntensity;
    }
    void uniformSets;
    if (group.current) {
      // The whole rig counter-rotates very slowly; parallax against the
      // carousel is what sells the depth of the volume.
      group.current.rotation.y = t * 0.006;
    }
  });

  return (
    <group ref={group} renderOrder={-200}>
      {beams.map((b, i) => (
        <mesh
          key={i}
          position={b.position}
          rotation={b.rotation}
          frustumCulled={false}
          scale={[1, 1, 1]}
        >
          {/* Open-ended cone: radius tapers toward the floor. */}
          <cylinderGeometry args={[b.radius * 0.12, b.radius, b.length, 20, 1, true]} />
          <shaderMaterial
            ref={(m) => {
              if (m) materials.current[i] = m;
            }}
            vertexShader={BEAM_VERT}
            fragmentShader={BEAM_FRAG}
            uniforms={uniformSets[i]}
            transparent
            depthWrite={false}
            side={DoubleSide}
            blending={AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      ))}
    </group>
  );
}
