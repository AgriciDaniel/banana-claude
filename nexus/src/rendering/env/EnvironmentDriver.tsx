'use client';

import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Color } from 'three';
import { ENVIRONMENTS, MODULE_WORLDS, type EnvironmentId } from '@/config/environments';
import { envRuntime, useEnvironmentStore } from '@/stores/useEnvironmentStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { bus } from '@/stores/bus';
import { damp } from '@/core/math';
import { log } from '@/stores/useLogStore';
import { t } from '@/i18n';
import { getAudio } from '@/audio/AudioEngine';

/**
 * The world morph.
 *
 * Interpolates every environment parameter toward the active preset, once per
 * frame, in place. Consumers read `envRuntime` and never know a transition is
 * happening - which is why adding an environment-aware component later costs
 * nothing.
 *
 * Two things decide the target: what the user picked, and whether an expanded
 * module has claimed the world. The module wins while it is open and hands the
 * world back when it closes.
 */

/** Morph rate. Slow enough to read as a camera move, fast enough not to drag. */
const LAMBDA = 1.15;

/** Module-scope scratch colour, reused every frame. */
const TMP = new Color();

/** Manhattan distance in RGB. Cheap, and precise enough to time a transition. */
function colorGap(a: Color, b: Color): number {
  return Math.abs(a.r - b.r) + Math.abs(a.g - b.g) + Math.abs(a.b - b.b);
}

export function EnvironmentDriver() {
  const preferred = useEnvironmentStore((s) => s.preferred);
  const active = useEnvironmentStore((s) => s.active);
  const setActive = useEnvironmentStore((s) => s.setActive);
  const setMorphing = useEnvironmentStore((s) => s.setMorphing);
  const expandedId = useCarouselStore((s) => s.expandedId);

  const distance = useRef(0);
  const wasMorphing = useRef(false);

  // Decide the world. Expanding a bound module pulls it; collapsing releases.
  useEffect(() => {
    const claimed = expandedId ? MODULE_WORLDS[expandedId] : undefined;
    const next: EnvironmentId = claimed ?? preferred;
    if (next === active) return;

    setActive(next, claimed ? expandedId : null);
    bus.emit('env:change', { id: next, source: claimed ? 'module' : 'user' });
    getAudio().morph();
    log.sys(t('log.world', { world: ENVIRONMENTS[next].name.toUpperCase() }));
  }, [expandedId, preferred, active, setActive]);

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const target = ENVIRONMENTS[active];
    const e = envRuntime;
    const k = 1 - Math.exp(-LAMBDA * dt);

    e.deep.lerp(TMP.set(target.deep), k);
    e.mid.lerp(TMP.set(target.mid), k);
    e.glow.lerp(TMP.set(target.glow), k);
    e.grid.lerp(TMP.set(target.grid), k);
    e.beamColor.lerp(TMP.set(target.beamColor), k);
    e.moteCore.lerp(TMP.set(target.moteCore), k);
    e.moteEdge.lerp(TMP.set(target.moteEdge), k);
    e.keyColor.lerp(TMP.set(target.keyColor), k);
    e.fillColor.lerp(TMP.set(target.fillColor), k);

    e.density = damp(e.density, target.density, LAMBDA, dt);
    e.fog = damp(e.fog, target.fog, LAMBDA, dt);
    e.horizon = damp(e.horizon, target.horizon, LAMBDA, dt);
    e.gridSpacing = damp(e.gridSpacing, target.gridSpacing, LAMBDA, dt);
    e.gridStrength = damp(e.gridStrength, target.gridStrength, LAMBDA, dt);
    e.floorY = damp(e.floorY, target.floorY, LAMBDA, dt);
    e.beamScale = damp(e.beamScale, target.beamScale, LAMBDA, dt);
    e.beamIntensity = damp(e.beamIntensity, target.beamIntensity, LAMBDA, dt);
    e.moteDrift = damp(e.moteDrift, target.moteDrift, LAMBDA, dt);
    e.moteSize = damp(e.moteSize, target.moteSize, LAMBDA, dt);
    e.moteOpacity = damp(e.moteOpacity, target.moteOpacity, LAMBDA, dt);
    e.ambient = damp(e.ambient, target.ambient, LAMBDA, dt);
    e.keyIntensity = damp(e.keyIntensity, target.keyIntensity, LAMBDA, dt);
    e.fillIntensity = damp(e.fillIntensity, target.fillIntensity, LAMBDA, dt);
    e.envIntensity = damp(e.envIntensity, target.envIntensity, LAMBDA, dt);

    /*
     * How far the world still has to travel, normalised. This single number
     * drives every transition effect - the shockwave, the mote turbulence, the
     * lens swell - so they stay in sync with the morph automatically instead of
     * each running its own timer against its own easing.
     */
    const remaining =
      Math.abs(e.fog - target.fog) / 0.09 +
      Math.abs(e.gridSpacing - target.gridSpacing) / 1.5 +
      colorGap(e.deep, TMP.set(target.deep)) * 3 +
      colorGap(e.glow, TMP.set(target.glow)) * 3;

    distance.current = damp(distance.current, remaining, 8, dt);
    e.morph = Math.min(1, distance.current);

    const morphing = e.morph > 0.06;
    if (morphing !== wasMorphing.current) {
      wasMorphing.current = morphing;
      setMorphing(morphing);
    }
  }, -95);

  return null;
}
