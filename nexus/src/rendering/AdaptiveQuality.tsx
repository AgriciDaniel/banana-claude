'use client';

import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useSystemStore } from '@/stores/useSystemStore';
import { tierDown, tierUp, QUALITY_PROFILES } from '@/config/quality';
import { perf } from '@/stores/runtime';
import { bus } from '@/stores/bus';
import { log } from '@/stores/useLogStore';
import { t } from '@/i18n';
import { RollingMean } from '@/core/math';
import type { QualityTier } from '@/core/types';

/**
 * Frame-rate governor.
 *
 * Two rules keep this from becoming the thing that ruins the experience:
 *
 *   1. Asymmetric hysteresis. Dropping a tier needs 1.5 s of sustained pain;
 *      climbing back needs 6 s of comfortable headroom. Quality oscillating
 *      once a second is far worse than simply running one tier low.
 *   2. A cooldown after every change, because the frame right after a tier
 *      switch is always slow (shader recompiles, buffer reallocation) and
 *      would otherwise immediately trigger another drop.
 *   3. A one-way ratchet. A tier that has already failed on this device is
 *      never auto-entered again. Without this the governor oscillates forever:
 *      HIGH runs at 90 fps, so it climbs to ULTRA, which runs at 33, so it
 *      drops back to HIGH, which runs at 90... The GPU is not going to get
 *      faster during the session, so the first failure is the answer.
 *      Manual override stays available by turning auto-quality off.
 */

const DROP_BELOW = 46;
const RAISE_ABOVE = 58;
const DROP_SUSTAIN_MS = 1500;
const RAISE_SUSTAIN_MS = 6000;
const COOLDOWN_MS = 2500;

export function AdaptiveQuality() {
  const gl = useThree((s) => s.gl);
  const setDpr = useThree((s) => s.setDpr);
  const tier = useSystemStore((s) => s.tier);
  const autoQuality = useSystemStore((s) => s.autoQuality);
  const setTier = useSystemStore((s) => s.setTier);

  const mean = useRef(new RollingMean(60));
  const badSince = useRef(0);
  const goodSince = useRef(0);
  const changedAt = useRef(0);
  /** Tiers that have already proven too expensive on this device. */
  const failed = useRef(new Set<QualityTier>());

  // The renderer's pixel ratio is the cheapest, highest-leverage dial there is,
  // so it is applied immediately on every tier change.
  useEffect(() => {
    const profile = QUALITY_PROFILES[tier];
    const ceiling = Math.min(profile.dpr, window.devicePixelRatio || 1);
    setDpr(ceiling);
    gl.setPixelRatio(ceiling);
  }, [tier, gl, setDpr]);

  useFrame(() => {
    if (!autoQuality) return;
    const now = performance.now();
    if (now - changedAt.current < COOLDOWN_MS) {
      badSince.current = 0;
      goodSince.current = 0;
      return;
    }

    const fps = mean.current.push(perf.fps);
    if (!mean.current.saturated) return;

    if (fps < DROP_BELOW) {
      goodSince.current = 0;
      if (badSince.current === 0) badSince.current = now;
      else if (now - badSince.current > DROP_SUSTAIN_MS) {
        const next = tierDown(tier);
        if (next !== tier) {
          failed.current.add(tier);
          setTier(next, true);
          changedAt.current = now;
          mean.current.reset();
          bus.emit('quality:change', { tier: next, direction: 'down' });
          log.warn(t('log.qualityDown', { tier: t(`tier.${next}`), fps: fps.toFixed(0) }));
        }
        badSince.current = 0;
      }
      return;
    }

    if (fps > RAISE_ABOVE) {
      badSince.current = 0;
      const candidate = tierUp(tier);
      // Already tried and rejected — running one tier low is strictly better
      // than visibly flip-flopping between two.
      if (failed.current.has(candidate)) {
        goodSince.current = 0;
        return;
      }
      if (goodSince.current === 0) goodSince.current = now;
      else if (now - goodSince.current > RAISE_SUSTAIN_MS) {
        const next = candidate;
        if (next !== tier) {
          setTier(next, true);
          changedAt.current = now;
          mean.current.reset();
          bus.emit('quality:change', { tier: next, direction: 'up' });
          log.sys(t('log.qualityUp', { tier: t(`tier.${next}`) }));
        }
        goodSince.current = 0;
      }
      return;
    }

    badSince.current = 0;
    goodSince.current = 0;
  });

  return null;
}
