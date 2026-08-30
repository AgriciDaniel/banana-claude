'use client';

import { create } from 'zustand';
import type { BootPhase, InputSource, QualityTier, TrackingStatus } from '@/core/types';
import type { DeviceCapabilities } from '@/core/capabilities';
import { QUALITY_PROFILES, type QualityProfile } from '@/config/quality';

interface SystemState {
  boot: BootPhase;
  capabilities: DeviceCapabilities | null;
  tier: QualityTier;
  profile: QualityProfile;
  /** When true the governor may change `tier` on its own. */
  autoQuality: boolean;
  tracking: TrackingStatus;
  trackingError: string | null;
  input: InputSource;
  audio: boolean;
  audioUnlocked: boolean;
  hud: boolean;
  /** Debug overlays: hand skeleton, slot markers. */
  diagnostics: boolean;

  setBoot: (b: BootPhase) => void;
  setCapabilities: (c: DeviceCapabilities) => void;
  setTier: (t: QualityTier, auto?: boolean) => void;
  setAutoQuality: (v: boolean) => void;
  setTracking: (s: TrackingStatus, error?: string | null) => void;
  setInput: (s: InputSource) => void;
  toggleAudio: () => void;
  setAudioUnlocked: (v: boolean) => void;
  toggleHud: () => void;
  toggleDiagnostics: () => void;
}

export const useSystemStore = create<SystemState>((set) => ({
  boot: 'cold',
  capabilities: null,
  tier: 'high',
  profile: QUALITY_PROFILES.high,
  autoQuality: true,
  tracking: 'idle',
  trackingError: null,
  input: 'none',
  audio: true,
  audioUnlocked: false,
  hud: true,
  diagnostics: false,

  setBoot: (boot) => set({ boot }),
  setCapabilities: (capabilities) =>
    set({
      capabilities,
      tier: capabilities.suggestedTier,
      profile: QUALITY_PROFILES[capabilities.suggestedTier],
    }),
  setTier: (tier, auto = false) =>
    set((s) => (auto && !s.autoQuality ? s : { tier, profile: QUALITY_PROFILES[tier] })),
  setAutoQuality: (autoQuality) => set({ autoQuality }),
  setTracking: (tracking, trackingError = null) => set({ tracking, trackingError }),
  setInput: (input) => set({ input }),
  toggleAudio: () => set((s) => ({ audio: !s.audio })),
  setAudioUnlocked: (audioUnlocked) => set({ audioUnlocked }),
  toggleHud: () => set((s) => ({ hud: !s.hud })),
  toggleDiagnostics: () => set((s) => ({ diagnostics: !s.diagnostics })),
}));
