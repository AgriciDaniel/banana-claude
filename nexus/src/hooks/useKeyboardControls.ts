'use client';

import { useEffect } from 'react';
import { MODULES } from '@/config/modules';
import { ring } from '@/scene/ringController';
import { interaction } from '@/stores/runtime';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { getAudio } from '@/audio/AudioEngine';
import { log } from '@/stores/useLogStore';
import { t, useLocaleStore } from '@/i18n';
import { localizeModule } from '@/i18n/modules';

/**
 * Keyboard control surface.
 *
 * Not a fallback so much as an accessibility floor: every gesture in the
 * system has a key, so the OS is fully operable without a camera, without a
 * mouse, and by anyone who cannot comfortably hold a hand in the air.
 */
const nameOf = (index: number) => {
  const mod = MODULES[index];
  if (!mod) return '';
  return localizeModule(mod, useLocaleStore.getState().locale).name.toUpperCase();
};

export function useKeyboardControls() {
  useEffect(() => {
    const audio = getAudio();

    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const cards = useCarouselStore.getState();
      const system = useSystemStore.getState();

      switch (e.key) {
        case 'ArrowLeft':
          e.preventDefault();
          ring.rotate(1, 1);
          audio.whoosh(-1, 0.8);
          break;

        case 'ArrowRight':
          e.preventDefault();
          ring.rotate(-1, 1);
          audio.whoosh(1, 0.8);
          break;

        case 'ArrowUp':
        case ' ': {
          e.preventDefault();
          const id = MODULES[cards.focusedIndex]?.id;
          if (!id) break;
          if (cards.expandedId === id) {
            cards.collapse();
            audio.collapse();
          } else {
            cards.expand(id);
            audio.expand();
            log.ok(t('log.expand', { module: nameOf(cards.focusedIndex) }));
          }
          break;
        }

        case 'ArrowDown':
        case 'Escape':
          e.preventDefault();
          if (cards.expandedId) {
            cards.collapse();
            audio.collapse();
          } else if (cards.selectedId) {
            cards.select(null);
          }
          break;

        case 'Enter': {
          const id = MODULES[cards.focusedIndex]?.id ?? null;
          cards.select(cards.selectedId === id ? null : id);
          audio.confirm();
          break;
        }

        case 'f':
        case 'F': {
          const next = !interaction.frozen;
          interaction.frozen = next;
          ring.setLocked(next);
          if (next) audio.freeze();
          else audio.thaw();
          log[next ? 'warn' : 'ok'](t(next ? 'log.frozenManual' : 'log.resumed'));
          break;
        }

        case 'h':
        case 'H':
          system.toggleHud();
          audio.tick();
          break;

        case 'd':
        case 'D':
          system.toggleDiagnostics();
          audio.tick();
          break;

        case 'm':
        case 'M':
          system.toggleAudio();
          break;

        default: {
          // 1..9 then 0 jump straight to a module.
          if (!/^[0-9]$/.test(e.key)) return;
          const n = e.key === '0' ? 9 : Number(e.key) - 1;
          if (n >= MODULES.length) return;
          ring.focus(n);
          audio.tick();
          log.sys(t('log.focus', { module: nameOf(n) }));
        }
      }
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
