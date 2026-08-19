'use client';

import { useEffect } from 'react';
import { bus } from '@/stores/bus';
import { getAudio } from '@/audio/AudioEngine';
import { useSystemStore } from '@/stores/useSystemStore';
import { log } from '@/stores/useLogStore';
import { moduleById } from '@/config/modules';
import { t, useLocaleStore } from '@/i18n';
import { localizeModule } from '@/i18n/modules';

/**
 * Audio bindings.
 *
 * The audio engine is deaf to application state by design; this hook is the
 * only thing that translates events into sound. Keeping it in one place means
 * the entire sonic signature of the OS can be re-scored without touching a
 * single interaction handler.
 */
export function useAudioBindings() {
  const muted = !useSystemStore((s) => s.audio);
  const unlocked = useSystemStore((s) => s.audioUnlocked);

  useEffect(() => {
    getAudio().setMuted(muted);
  }, [muted, unlocked]);

  useEffect(() => {
    const audio = getAudio();

    const offState = bus.on('card:state', ({ id, state }) => {
      if (state === 'selected') audio.confirm();
      const mod = moduleById(id);
      if (state === 'expanded' && mod) {
        const name = localizeModule(mod, useLocaleStore.getState().locale).name.toUpperCase();
        log.ok(t('log.surface', { module: name }));
      }
    });

    const offSettled = bus.on('card:settled', ({ id }) => {
      audio.tick();
      const mod = moduleById(id);
      const name = mod
        ? localizeModule(mod, useLocaleStore.getState().locale).name.toUpperCase()
        : id.toUpperCase();
      log.sys(t('log.recalled', { module: name }));
    });

    const offSnap = bus.on('carousel:snap', ({ index }) => {
      void index;
      audio.tick();
    });

    return () => {
      offState();
      offSettled();
      offSnap();
    };
  }, []);
}
