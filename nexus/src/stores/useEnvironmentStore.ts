'use client';

import { create } from 'zustand';
import { Color } from 'three';
import { ENVIRONMENTS, type Environment, type EnvironmentId } from '@/config/environments';

/**
 * Which world we are in, and which one we are becoming.
 *
 * The store holds only the discrete choice. The continuously interpolated
 * values live in `envRuntime` below, following the Phase 1 rule: anything that
 * changes every frame stays out of React.
 */

interface EnvironmentState {
  /** What the user picked. Module worlds are layered on top, not stored here. */
  preferred: EnvironmentId;
  /** What is actually being rendered, including any module override. */
  active: EnvironmentId;
  /** Non-null while a module is pulling the world. */
  overriddenBy: string | null;
  /** 0..1 progress of the current morph, mirrored for the HUD. */
  morphing: boolean;

  setPreferred: (id: EnvironmentId) => void;
  setActive: (id: EnvironmentId, overriddenBy: string | null) => void;
  setMorphing: (v: boolean) => void;
}

export const useEnvironmentStore = create<EnvironmentState>((set) => ({
  preferred: 'lab',
  active: 'lab',
  overriddenBy: null,
  morphing: false,

  setPreferred: (preferred) => set({ preferred }),
  setActive: (active, overriddenBy) => set({ active, overriddenBy }),
  setMorphing: (morphing) => set({ morphing }),
}));

/**
 * The live, interpolated world.
 *
 * Every environment-aware component reads from this object each frame instead
 * of from the preset, which is what makes a world change a morph rather than a
 * cut. Colours are three.js Colors so they can be lerped in place with no
 * allocation.
 */
export interface EnvRuntime {
  deep: Color;
  mid: Color;
  glow: Color;
  grid: Color;
  beamColor: Color;
  moteCore: Color;
  moteEdge: Color;
  keyColor: Color;
  fillColor: Color;

  density: number;
  fog: number;
  horizon: number;
  gridSpacing: number;
  gridStrength: number;
  floorY: number;
  beamScale: number;
  beamIntensity: number;
  moteDrift: number;
  moteSize: number;
  moteOpacity: number;
  ambient: number;
  keyIntensity: number;
  fillIntensity: number;
  envIntensity: number;

  /** 0..1, rises during a morph and falls after. Drives the transition FX. */
  morph: number;
}

function seed(from: Environment): EnvRuntime {
  return {
    deep: new Color(from.deep),
    mid: new Color(from.mid),
    glow: new Color(from.glow),
    grid: new Color(from.grid),
    beamColor: new Color(from.beamColor),
    moteCore: new Color(from.moteCore),
    moteEdge: new Color(from.moteEdge),
    keyColor: new Color(from.keyColor),
    fillColor: new Color(from.fillColor),

    density: from.density,
    fog: from.fog,
    horizon: from.horizon,
    gridSpacing: from.gridSpacing,
    gridStrength: from.gridStrength,
    floorY: from.floorY,
    beamScale: from.beamScale,
    beamIntensity: from.beamIntensity,
    moteDrift: from.moteDrift,
    moteSize: from.moteSize,
    moteOpacity: from.moteOpacity,
    ambient: from.ambient,
    keyIntensity: from.keyIntensity,
    fillIntensity: from.fillIntensity,
    envIntensity: from.envIntensity,
    morph: 0,
  };
}

export const envRuntime: EnvRuntime = seed(ENVIRONMENTS.lab);
