'use client';

import { useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  NormalBlending,
  Vector3,
  type PointLight,
  type ShaderMaterial,
} from 'three';
import { PRECIP_FRAG, PRECIP_VERT } from '@/shaders/precipitation';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { useFeedStore } from '@/modules/store';
import { envRuntime } from '@/stores/useEnvironmentStore';
import type { SkyCondition, WeatherData } from '@/modules/types';
import { damp, hash11 } from '@/core/math';

/**
 * The room has weather.
 *
 * This is the module that most obviously refuses to be a widget: instead of
 * drawing a cloud icon, the actual environment changes. Real precipitation
 * falls through the volume, fog thickens, the light warms or drains, and a
 * storm throws real light into the scene.
 *
 * Every parameter is driven from the live Open-Meteo feed, so if it is raining
 * where you are, it is raining in here.
 */

interface Mood {
  /** 0 = rain, 1 = snow. */
  mode: number;
  /** Fraction of the particle pool in use, 0..1. */
  amount: number;
  speed: number;
  /** Extra scene fog on top of the base density. */
  fog: number;
  /** Multiplier on ambient brightness. */
  light: number;
  storm: boolean;
  color: string;
}

const MOODS: Record<SkyCondition, Mood> = {
  clear: { mode: 0, amount: 0, speed: 0, fog: -0.012, light: 1.25, storm: false, color: PALETTE.lumen },
  cloud: { mode: 0, amount: 0, speed: 0, fog: 0.008, light: 0.9, storm: false, color: PALETTE.signal },
  fog: { mode: 0, amount: 0, speed: 0, fog: 0.05, light: 0.7, storm: false, color: PALETTE.signal },
  rain: { mode: 0, amount: 0.75, speed: 15, fog: 0.018, light: 0.72, storm: false, color: PALETTE.signal },
  snow: { mode: 1, amount: 0.6, speed: 2.6, fog: 0.026, light: 1.05, storm: false, color: PALETTE.lumen },
  storm: { mode: 0, amount: 1, speed: 21, fog: 0.03, light: 0.55, storm: true, color: PALETTE.signal },
};

const POOL = 4000;
const BOUNDS: [number, number, number] = [15, 11, 15];

export function WeatherSky() {
  const material = useRef<ShaderMaterial>(null);
  const flash = useRef<PointLight>(null);
  const scene = useThree((s) => s.scene);
  const profile = useSystemStore((s) => s.profile);

  const feed = useFeedStore((s) => s.feeds.weather);
  const weather = feed?.data as WeatherData | undefined;
  const condition: SkyCondition = weather?.condition ?? 'clear';
  const mood = MOODS[condition];

  /** Smoothed so a forecast refresh never snaps the room to a new mood. */
  const blend = useRef({ amount: 0, fog: 0, light: 1, nextFlash: 4 });

  const geometry = useMemo(() => {
    const count = Math.min(POOL, Math.max(900, Math.round(profile.particles * 0.7)));
    const geo = new BufferGeometry();
    const position = new Float32Array(count * 3);
    const seed = new Float32Array(count * 3);
    const scale = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      seed[i * 3] = Math.random() * 2 - 1;
      seed[i * 3 + 1] = Math.random() * 2 - 1;
      seed[i * 3 + 2] = Math.random() * 2 - 1;
      // Uniform in 0..1 so `aScale < uAmount` is a fair intensity gate.
      scale[i] = hash11(i * 1.37 + 0.5);
    }
    geo.setAttribute('position', new BufferAttribute(position, 3));
    geo.setAttribute('aSeed', new BufferAttribute(seed, 3));
    geo.setAttribute('aScale', new BufferAttribute(scale, 1));
    geo.boundingSphere = null;
    return geo;
  }, [profile.particles]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uBounds: { value: new Vector3(...BOUNDS) },
      uMode: { value: 0 },
      uSpeed: { value: 14 },
      uWind: { value: 0.4 },
      uAmount: { value: 0 },
      uFreeze: { value: 0 },
      uColor: { value: new Color(PALETTE.signal) },
      uOpacity: { value: 0.5 },
    }),
    [],
  );

  useFrame((_, delta) => {
    if (!material.current) return;
    const dt = delta > 0.05 ? 0.05 : delta;
    const b = blend.current;
    const u = material.current.uniforms;

    b.amount = damp(b.amount, mood.amount, 1.1, dt);
    b.fog = damp(b.fog, mood.fog, 0.9, dt);
    b.light = damp(b.light, mood.light, 0.9, dt);

    u.uTime.value = interaction.sceneTime;
    u.uFreeze.value = interaction.freezeBlend;
    u.uAmount.value = b.amount;
    u.uMode.value = damp(u.uMode.value as number, mood.mode, 1.6, dt);
    u.uSpeed.value = damp(u.uSpeed.value as number, Math.max(mood.speed, 0.1), 1.2, dt);
    // Real wind, from the real forecast.
    u.uWind.value = damp(u.uWind.value as number, (weather?.wind ?? 0) / 55, 0.8, dt);
    (u.uColor.value as Color).lerp(new Color(mood.color), dt * 1.2);
    u.uOpacity.value = mood.mode > 0.5 ? 0.75 : 0.42;

    // Fog belongs to the scene, not to this mesh: thickening it is what makes
    // the whole room feel weathered rather than just rained on.
    /*
     * Weather is a DELTA on the world, not a replacement for it. The Fog
     * Chamber in the rain should be thicker than the Studio in the rain, and
     * adding to the environment's own density is what preserves that.
     */
    const fog = scene.fog as { density?: number; color?: { copy: (c: unknown) => void } } | null;
    if (fog && typeof fog.density === 'number') {
      fog.density = Math.max(0.004, envRuntime.fog + b.fog);
      fog.color?.copy(envRuntime.deep);
    }

    // Lightning. Irregular on purpose - a metronome reads as a strobe effect.
    if (flash.current) {
      if (mood.storm) {
        b.nextFlash -= dt;
        if (b.nextFlash <= 0) {
          flash.current.intensity = 260 + Math.random() * 420;
          b.nextFlash = 2.6 + Math.random() * 7;
        }
        flash.current.intensity *= Math.pow(0.008, dt);
      } else {
        flash.current.intensity = damp(flash.current.intensity, 0, 6, dt);
      }
    }
  });

  return (
    <group name="weather">
      <points geometry={geometry} frustumCulled={false} renderOrder={-60}>
        <shaderMaterial
          ref={material}
          vertexShader={PRECIP_VERT}
          fragmentShader={PRECIP_FRAG}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          blending={mood.mode > 0.5 ? NormalBlending : AdditiveBlending}
          toneMapped={false}
        />
      </points>

      {/* Storm light. High above and off to one side, like real sheet lightning. */}
      <pointLight
        ref={flash}
        position={[-6, 9, -4]}
        intensity={0}
        distance={60}
        decay={1.4}
        color={PALETTE.lumen}
      />
    </group>
  );
}
