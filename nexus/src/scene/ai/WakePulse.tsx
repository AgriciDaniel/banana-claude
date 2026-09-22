'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  BackSide,
  Color,
  DoubleSide,
  type Mesh,
  type ShaderMaterial,
} from 'three';
import { RIPPLE_FRAG, RIPPLE_VERT, WAKE_FRAG, WAKE_VERT } from '@/shaders/wake';
import { PALETTE } from '@/config/theme';
import { interaction, voice } from '@/stores/runtime';
import { bus } from '@/stores/bus';
import { damp } from '@/core/math';

/**
 * Waking the assistant.
 *
 * Two coordinated events plus a persistent state:
 *
 *   - a shell of light leaves the centre and passes outward through the room;
 *   - a ripple travels across the implied floor beneath the ring;
 *   - while awake, the whole volume sits fractionally brighter and cooler.
 *
 * The last one is the important one. A flash is a notification; a sustained
 * change in the light is the environment behaving differently because someone
 * is now listening.
 */

/** Seconds for the wavefront to cross the room. */
const WAVE_S = 1.5;
const MAX_RADIUS = 26;
const FLOOR_Y = -3.05;

export function WakePulse() {
  const shell = useRef<Mesh>(null);
  const ripple = useRef<Mesh>(null);
  const glow = useRef<Mesh>(null);

  const progress = useRef(1);

  const shellUniforms = useMemo(
    () => ({
      uColor: { value: new Color(PALETTE.signal) },
      uProgress: { value: 1 },
      uIntensity: { value: 0.9 },
    }),
    [],
  );

  const rippleUniforms = useMemo(
    () => ({
      uColor: { value: new Color(PALETTE.signal) },
      uProgress: { value: 1 },
      uRadius: { value: MAX_RADIUS },
      uIntensity: { value: 1 },
    }),
    [],
  );

  useEffect(() => {
    const off = bus.on('ai:wake', () => {
      progress.current = 0;
      voice.wakeAt = interaction.sceneTime;
    });
    return off;
  }, []);

  useFrame((_, delta) => {
    const awake = voice.awakeBlend;

    // --- travelling wave ---------------------------------------------------
    if (progress.current < 1) {
      progress.current = Math.min(1, progress.current + delta / WAVE_S);
      const p = progress.current;
      // Ease out: the front decelerates as it dissipates into the fog.
      const eased = 1 - Math.pow(1 - p, 2.2);

      shellUniforms.uProgress.value = p;
      rippleUniforms.uProgress.value = p;

      if (shell.current) {
        const r = 0.4 + eased * MAX_RADIUS;
        shell.current.scale.setScalar(r);
        shell.current.visible = true;
      }
      if (ripple.current) ripple.current.visible = true;
    } else {
      if (shell.current) shell.current.visible = false;
      if (ripple.current) ripple.current.visible = false;
    }

    // --- sustained awake glow ---------------------------------------------
    if (glow.current) {
      const material = glow.current.material as ShaderMaterial & { opacity: number };
      // Speech modulates it, so the room brightens on the assistant's voice.
      const target = awake * (0.06 + voice.level * 0.09);
      material.opacity = damp(material.opacity ?? 0, target, 5, delta);
      glow.current.visible = material.opacity > 0.002;
    }
  });

  return (
    <group name="wake">
      {/* Expanding shell. Unit sphere, scaled — one geometry, any radius. */}
      <mesh ref={shell} visible={false} frustumCulled={false} renderOrder={-90}>
        <sphereGeometry args={[1, 40, 28]} />
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

      {/* Floor ripple, coplanar with the grid. */}
      <mesh
        ref={ripple}
        visible={false}
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, FLOOR_Y, 0]}
        renderOrder={-80}
      >
        <planeGeometry args={[MAX_RADIUS * 2, MAX_RADIUS * 2, 1, 1]} />
        <shaderMaterial
          vertexShader={RIPPLE_VERT}
          fragmentShader={RIPPLE_FRAG}
          uniforms={rippleUniforms}
          transparent
          depthWrite={false}
          side={DoubleSide}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>

      {/*
        The "interface glows" state. An inward-facing shell washing the whole
        volume in signal blue — it lifts everything at once without any Phase 1
        material needing to know the assistant exists.
      */}
      <mesh ref={glow} visible={false} frustumCulled={false} renderOrder={-95}>
        <sphereGeometry args={[42, 24, 16]} />
        <meshBasicMaterial
          color={PALETTE.signal}
          transparent
          opacity={0}
          side={BackSide}
          depthWrite={false}
          depthTest={false}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}
