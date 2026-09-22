import type { QualityTier } from '@/core/types';

/**
 * Adaptive quality ladder.
 *
 * The governor in `rendering/AdaptiveQuality.tsx` walks this ladder up and
 * down based on sustained frame time. Every visual subsystem reads its budget
 * from here — nothing hardcodes a particle count.
 */
export interface QualityProfile {
  tier: QualityTier;
  /** Device pixel ratio ceiling. */
  dpr: number;
  /** Drifting motes in the volume. */
  particles: number;
  /** Volumetric light beams. */
  beams: number;
  bloom: boolean;
  bloomLevels: number;
  depthOfField: boolean;
  chromaticAberration: boolean;
  filmGrain: boolean;
  /** Real refraction on the card glass — the single most expensive feature. */
  transmission: boolean;
  transmissionSamples: number;
  /** Card reflections sample an env map instead of a live probe when false. */
  liveReflections: boolean;
  /** Rapier physics substeps for released cards. */
  physicsSubsteps: number;
  /** Trails behind dragged cards. */
  trails: boolean;
  shadowMap: boolean;
}

export const QUALITY_PROFILES: Record<QualityTier, QualityProfile> = {
  low: {
    tier: 'low',
    dpr: 1,
    particles: 900,
    beams: 3,
    bloom: true,
    bloomLevels: 4,
    depthOfField: false,
    chromaticAberration: false,
    filmGrain: false,
    transmission: false,
    transmissionSamples: 0,
    liveReflections: false,
    physicsSubsteps: 1,
    trails: false,
    shadowMap: false,
  },
  medium: {
    tier: 'medium',
    dpr: 1.25,
    particles: 2200,
    beams: 4,
    bloom: true,
    bloomLevels: 5,
    depthOfField: false,
    chromaticAberration: true,
    filmGrain: true,
    transmission: false,
    transmissionSamples: 0,
    liveReflections: false,
    physicsSubsteps: 1,
    trails: true,
    shadowMap: false,
  },
  high: {
    tier: 'high',
    dpr: 1.5,
    particles: 4200,
    beams: 6,
    bloom: true,
    bloomLevels: 6,
    depthOfField: false,
    chromaticAberration: true,
    filmGrain: true,
    transmission: true,
    transmissionSamples: 4,
    liveReflections: false,
    physicsSubsteps: 2,
    trails: true,
    shadowMap: false,
  },
  ultra: {
    tier: 'ultra',
    dpr: 2,
    particles: 6400,
    beams: 8,
    bloom: true,
    bloomLevels: 7,
    depthOfField: true,
    chromaticAberration: true,
    filmGrain: true,
    transmission: true,
    transmissionSamples: 8,
    liveReflections: true,
    physicsSubsteps: 2,
    trails: true,
    shadowMap: false,
  },
};

export const TIER_ORDER: QualityTier[] = ['low', 'medium', 'high', 'ultra'];

export function tierUp(t: QualityTier): QualityTier {
  const i = TIER_ORDER.indexOf(t);
  return TIER_ORDER[Math.min(i + 1, TIER_ORDER.length - 1)]!;
}

export function tierDown(t: QualityTier): QualityTier {
  const i = TIER_ORDER.indexOf(t);
  return TIER_ORDER[Math.max(i - 1, 0)]!;
}
