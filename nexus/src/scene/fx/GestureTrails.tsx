'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  Vector3,
  type Points,
  type ShaderMaterial,
} from 'three';
import { PALETTE } from '@/config/theme';
import { interaction, voice } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';
import { useCarouselStore } from '@/stores/useCarouselStore';

/**
 * Motion leaves light behind.
 *
 * A ring buffer of motes emitted along the aim point's path, each fading over
 * a fixed lifetime. Emission rate follows speed, so a slow hand leaves almost
 * nothing and a fast swipe draws a bright arc — the trail reports how hard you
 * moved rather than merely that you did.
 *
 * One buffer, one draw call, no allocation after mount. Dead motes are not
 * removed; their age simply passes the lifetime and the shader discards them.
 */

const POOL = 220;
const LIFETIME = 0.85;
/** Below this world-units-per-second nothing is emitted. */
const MIN_SPEED = 0.9;

const TRAIL_VERT = /* glsl */ `
uniform float uTime;
uniform float uSize;

attribute float aBorn;
attribute float aSeed;
attribute float aPower;

varying float vAge;
varying float vPower;

void main() {
  float age = (uTime - aBorn) / ${LIFETIME.toFixed(2)};
  vAge = age;
  vPower = aPower;

  vec3 pos = position;
  // Trails drift upward and outward as they die, like settling sparks.
  pos.y += age * age * 0.28;
  pos.x += sin(aSeed * 31.0 + age * 3.0) * age * 0.09;
  pos.z += cos(aSeed * 17.0 + age * 2.4) * age * 0.09;

  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * (0.35 + aPower) * (1.0 - age * 0.55) * (200.0 / max(-mv.z, 0.001));
}
`;

const TRAIL_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform vec3 uHot;

varying float vAge;
varying float vPower;

void main() {
  if (vAge < 0.0 || vAge > 1.0) discard;

  vec2 uv = gl_PointCoord - 0.5;
  float r = dot(uv, uv) * 4.0;
  if (r > 1.0) discard;

  float body = pow(1.0 - r, 2.2);
  // Young sparks run white-hot and cool into the world's colour as they fade.
  vec3 color = mix(uHot, uColor, clamp(vAge * 1.6, 0.0, 1.0));
  float alpha = body * (1.0 - vAge) * (1.0 - vAge) * (0.35 + vPower * 0.9);
  if (alpha < 0.004) discard;

  gl_FragColor = vec4(color * (1.0 + (1.0 - vAge) * 0.8), alpha);
}
`;

const previous = new Vector3();
const current = new Vector3();

export function GestureTrails() {
  const points = useRef<Points>(null);
  const material = useRef<ShaderMaterial>(null);
  const cursor = useRef(0);
  const primed = useRef(false);
  const dragging = useCarouselStore((s) => s.draggingId !== null);

  const geometry = useMemo(() => {
    const geo = new BufferGeometry();
    const position = new Float32Array(POOL * 3);
    const born = new Float32Array(POOL).fill(-999);
    const seed = new Float32Array(POOL);
    const power = new Float32Array(POOL);
    for (let i = 0; i < POOL; i++) seed[i] = Math.random();

    geo.setAttribute('position', new BufferAttribute(position, 3));
    geo.setAttribute('aBorn', new BufferAttribute(born, 1));
    geo.setAttribute('aSeed', new BufferAttribute(seed, 1));
    geo.setAttribute('aPower', new BufferAttribute(power, 1));
    geo.boundingSphere = null;
    return geo;
  }, []);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: 3.2 },
      uColor: { value: new Color(PALETTE.signal) },
      uHot: { value: new Color(PALETTE.lumen) },
    }),
    [],
  );

  useFrame((_, delta) => {
    const mat = material.current;
    if (!mat) return;
    const now = interaction.sceneTime;
    mat.uniforms.uTime.value = now;
    (mat.uniforms.uColor.value as Color).copy(envRuntime.glow);

    current.set(interaction.aimX, interaction.aimY, interaction.aimZ);
    if (!primed.current) {
      previous.copy(current);
      primed.current = true;
      return;
    }

    const travelled = current.distanceTo(previous);
    const speed = travelled / Math.max(delta, 1e-3);
    previous.copy(current);

    if (speed < MIN_SPEED) return;

    /*
     * Emit along the segment just travelled rather than at a single point.
     * Sampling only at frame times leaves visible gaps at speed - the trail
     * becomes a dotted line - so the gap is subdivided.
     */
    const strength = Math.min(1, speed / 9) * (dragging ? 1 : 0.65) * (1 + voice.level * 0.4);
    const steps = Math.min(6, 1 + Math.floor(travelled / 0.07));

    const positions = geometry.getAttribute('position') as BufferAttribute;
    const born = geometry.getAttribute('aBorn') as BufferAttribute;
    const power = geometry.getAttribute('aPower') as BufferAttribute;
    const posArray = positions.array as Float32Array;
    const bornArray = born.array as Float32Array;
    const powerArray = power.array as Float32Array;

    for (let s = 0; s < steps; s++) {
      const i = cursor.current;
      cursor.current = (cursor.current + 1) % POOL;
      const t = s / steps;

      posArray[i * 3] = previous.x + (current.x - previous.x) * t;
      posArray[i * 3 + 1] = previous.y + (current.y - previous.y) * t;
      posArray[i * 3 + 2] = previous.z + (current.z - previous.z) * t;
      // Sub-frame timestamps, so a burst does not all die on the same frame.
      bornArray[i] = now - delta * (1 - t);
      powerArray[i] = strength;
    }

    positions.needsUpdate = true;
    born.needsUpdate = true;
    power.needsUpdate = true;
  });

  return (
    <points ref={points} geometry={geometry} frustumCulled={false} renderOrder={850}>
      <shaderMaterial
        ref={material}
        vertexShader={TRAIL_VERT}
        fragmentShader={TRAIL_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        depthTest={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}
