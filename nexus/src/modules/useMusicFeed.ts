'use client';

import { useEffect, useRef, useState } from 'react';
import type { ModuleFeed, MusicData } from './types';
import { getAudio } from '@/audio/AudioEngine';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { useSystemStore } from '@/stores/useSystemStore';

const BANDS = 32;

/**
 * Music.
 *
 * Not a player, and not a fake now-playing card. This is a real spectrum
 * analyser on the environment's own output: the ambient pad, the sub drone,
 * the air layer, every UI voice and the assistant when it speaks all pass
 * through the same master bus this reads.
 *
 * Sampled at 20 Hz and quantised, because a React tree does not need 60 Hz
 * updates to draw thirty-two bars convincingly.
 */
export function useMusicFeed(active: boolean): ModuleFeed<MusicData> {
  const audioOn = useSystemStore((s) => s.audio);
  const unlocked = useSystemStore((s) => s.audioUnlocked);
  const assistantStatus = useAssistantStore((s) => s.status);
  const [spectrum, setSpectrum] = useState<number[]>(() => new Array(BANDS).fill(0));
  const [level, setLevel] = useState(0);
  const buffer = useRef(new Float32Array(BANDS));

  useEffect(() => {
    if (!active || !unlocked) return;
    const audio = getAudio();
    const timer = window.setInterval(() => {
      if (!audio.spectrum(buffer.current)) return;
      // Quantise so unchanged bars do not re-render.
      setSpectrum(Array.from(buffer.current, (v) => Math.round(v * 40) / 40));
      setLevel(Math.round(audio.masterLevel() * 40) / 40);
    }, 50);
    return () => window.clearInterval(timer);
  }, [active, unlocked]);

  const speaking = assistantStatus === 'speaking';
  const sources = [
    ...(audioOn && unlocked ? ['Ambient pad', 'Sub drone', 'Air layer'] : []),
    ...(speaking ? ['Assistant voice'] : []),
  ];

  return {
    status: unlocked ? 'live' : 'unconfigured',
    error: null,
    fetchedAt: Date.now(),
    source: 'Web Audio master bus',
    setupHint: unlocked ? undefined : 'Audio is locked until you enter the environment.',
    data: { spectrum, level, sources, playing: audioOn && unlocked },
  };
}
