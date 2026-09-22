'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  Vector3,
  type ShaderMaterial,
} from 'three';
import { PARTICLE_FRAG, PARTICLE_VERT } from '@/shaders/particles';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { damp } from '@/core/math';
import { envRuntime } from '@/stores/useEnvironmentStore';

/**
 * The living air.
 *
 * One draw call, zero per-frame CPU work: seeds are uploaded once and the
 * vertex shader is a pure function of (seed, time). Changing the particle
 * budget rebuilds the buffer, which is why the quality governor only ever
 * touches it on an actual tier change and never per frame.
 */
export function ParticleField({ count = 4200, bounds = [16, 9, 16] as [number, number, number] }) {
  const material = useRef<ShaderMaterial>(null);
  const attract = useRef(0);

  const geometry = useMemo(() => {
    const geo = new BufferGeometry();
    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count * 3);
    const scales = new Float32Array(count);
    const phases = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      // Seeds are in -1..1 and scaled by uBounds in the shader, so the volume
      // can be reshaped without touching this buffer.
      const sx = Math.random() * 2 - 1;
      const sy = Math.random() * 2 - 1;
      const sz = Math.random() * 2 - 1;
      seeds[i * 3] = sx;
      seeds[i * 3 + 1] = sy;
      seeds[i * 3 + 2] = sz;

      // A few large motes carry the depth read; the rest are dust.
      const r = Math.random();
      scales[i] = r > 0.985 ? 2.6 + Math.random() * 1.6 : 0.35 + Math.pow(r, 3) * 1.15;
      phases[i] = Math.random();
    }

    geo.setAttribute('position', new BufferAttribute(positions, 3));
    geo.setAttribute('aSeed', new BufferAttribute(seeds, 3));
    geo.setAttribute('aScale', new BufferAttribute(scales, 1));
    geo.setAttribute('aPhase', new BufferAttribute(phases, 1));
    geo.boundingSphere = null;
    return geo;
  }, [count]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 2.4 },
      uBounds: { value: new Vector3(bounds[0], bounds[1], bounds[2]) },
      uDrift: { value: 1.35 },
      uFreeze: { value: 0 },
      uAttractor: { value: new Vector3() },
      uAttractStrength: { value: 0 },
      uColorCore: { value: new Color(PALETTE.lumen) },
      uColorEdge: { value: new Color(PALETTE.core) },
      uOpacity: { value: 0.85 },
    }),
    [bounds],
  );

  useFrame((_, delta) => {
    const mat = material.current;
    if (!mat) return;
    const uniforms = mat.uniforms;
    uniforms.uTime.value = interaction.sceneTime;
    uniforms.uFreeze.value = interaction.freezeBlend;

    // Motes take the world's colour and temperament.
    const e = envRuntime;
    (uniforms.uColorCore.value as Color).copy(e.moteCore);
    (uniforms.uColorEdge.value as Color).copy(e.moteEdge);
    uniforms.uSize.value = e.moteSize;
    uniforms.uOpacity.value = e.moteOpacity;
    /*
     * Drift surges during a morph. The air being disturbed is the clearest
     * signal that the room itself is changing, and it costs one multiply.
     */
    uniforms.uDrift.value = e.moteDrift * (1 + e.morph * 2.4);

    // Motes lean toward the active hand. The strength ramps rather than snaps
    // so losing tracking does not fling the whole field.
    const wanted = interaction.grabbedId ? 0.42 : 0.16;
    attract.current = damp(attract.current, wanted, 3.2, delta);
    uniforms.uAttractStrength.value = attract.current;

    const a = uniforms.uAttractor.value;
    a.x = damp(a.x, interaction.aimX, 7, delta);
    a.y = damp(a.y, interaction.aimY, 7, delta);
    a.z = damp(a.z, interaction.aimZ, 7, delta);
  });

  return (
    <points geometry={geometry} frustumCulled={false} renderOrder={-100}>
      <shaderMaterial
        ref={material}
        vertexShader={PARTICLE_VERT}
        fragmentShader={PARTICLE_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}
