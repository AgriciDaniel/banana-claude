'use client';

import { useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { AdditiveBlending, Color, DoubleSide, Vector3, type Group, type Mesh } from 'three';
import { PRESENCE_FRAG, PRESENCE_VERT } from '@/shaders/presence';
import { PALETTE } from '@/config/theme';
import { interaction, voice } from '@/stores/runtime';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { getAudio } from '@/audio/AudioEngine';
import { getGlowTexture } from '@/scene/glowTexture';
import { damp } from '@/core/math';

/**
 * The assistant, as an object in the room.
 *
 * Sits at the centre of the ring, which is also where its voice is
 * spatialised from - the sound and the shape are the same signal, so it reads
 * as one thing speaking rather than as a graphic with a soundtrack.
 *
 * This component also owns two pieces of global bookkeeping: it drives the
 * smoothed `awakeBlend` every other assistant visual reads, and it keeps the
 * Web Audio listener aligned with the drifting camera. Without the latter the
 * voice appears to swing around the room as the camera floats.
 */

/*
 * Centred horizontally, in front of the ring rather than at its geometric
 * centre. Dead centre put the orb behind the focused card, where it read as a
 * badge stuck on the glass instead of as a presence in the room.
 */
const CENTRE: [number, number, number] = [0, 0.72, 2.1];

const forward = new Vector3();

export function AiPresence() {
  const camera = useThree((s) => s.camera);
  const group = useRef<Group>(null);
  const core = useRef<Mesh>(null);
  const ringA = useRef<Mesh>(null);
  const ringB = useRef<Mesh>(null);
  const halo = useRef<Mesh>(null);

  const awake = useAssistantStore((s) => s.awake);
  const status = useAssistantStore((s) => s.status);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLevel: { value: 0 },
      uAwake: { value: 0 },
      uColor: { value: new Color(PALETTE.core) },
      uHot: { value: new Color(PALETTE.lumen) },
    }),
    [],
  );

  const glowTex = useMemo(() => getGlowTexture(), []);
  const thinking = status === 'thinking';

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const audio = getAudio();

    // Smoothed awake state — the single value every assistant visual reads.
    voice.awakeBlend = damp(voice.awakeBlend, awake ? 1 : 0, 3.4, dt);
    const blend = voice.awakeBlend;

    uniforms.uTime.value = interaction.sceneTime;
    uniforms.uAwake.value = blend;
    uniforms.uLevel.value = voice.level;

    // Keep the listener on the camera so the centre stays the centre.
    camera.getWorldDirection(forward);
    audio.setListener(
      camera.position.x,
      camera.position.y,
      camera.position.z,
      forward.x,
      forward.y,
      forward.z,
    );
    audio.setVoicePosition(CENTRE[0], CENTRE[1], CENTRE[2]);

    if (group.current) {
      // Rises slightly when awake, so the presence "sits up" to listen.
      const lift = CENTRE[1] + blend * 0.28;
      group.current.position.y = damp(group.current.position.y, lift, 4, dt);
      const scale = 0.34 + blend * 0.16 + voice.level * 0.07;
      group.current.scale.setScalar(damp(group.current.scale.x, scale, 8, dt));
    }

    const spin = interaction.sceneTime * (1 - interaction.freezeBlend * 0.9);
    if (ringA.current) {
      // Thinking spins the rings up: latency you can see is latency you can
      // tolerate.
      ringA.current.rotation.z = spin * (thinking ? 1.9 : 0.35);
      ringA.current.rotation.x = Math.PI / 2 + Math.sin(spin * 0.4) * 0.25;
    }
    if (ringB.current) {
      ringB.current.rotation.z = -spin * (thinking ? 1.35 : 0.22);
      ringB.current.rotation.y = Math.cos(spin * 0.33) * 0.4;
    }

    if (halo.current) {
      const material = halo.current.material as { opacity: number };
      material.opacity = damp(
        material.opacity,
        blend * (0.16 + voice.level * 0.5),
        6,
        dt,
      );
      const s = 2.6 + voice.level * 1.5;
      halo.current.scale.set(s, s, 1);
      halo.current.lookAt(camera.position);
    }

    if (core.current) core.current.visible = blend > 0.01;
  });

  return (
    <group ref={group} position={CENTRE} name="ai-presence">
      <mesh ref={core} frustumCulled={false}>
        <icosahedronGeometry args={[1, 5]} />
        <shaderMaterial
          vertexShader={PRESENCE_VERT}
          fragmentShader={PRESENCE_FRAG}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          side={DoubleSide}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>

      <mesh ref={ringA}>
        <torusGeometry args={[1.45, 0.012, 8, 96]} />
        <meshBasicMaterial
          color={PALETTE.signal}
          transparent
          opacity={0.5}
          blending={AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>

      <mesh ref={ringB}>
        <torusGeometry args={[1.85, 0.008, 8, 96]} />
        <meshBasicMaterial
          color={PALETTE.lumen}
          transparent
          opacity={0.3}
          blending={AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>

      <mesh ref={halo}>
        <planeGeometry args={[1, 1]} />
        <meshBasicMaterial
          map={glowTex}
          color={PALETTE.signal}
          transparent
          opacity={0}
          blending={AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}
