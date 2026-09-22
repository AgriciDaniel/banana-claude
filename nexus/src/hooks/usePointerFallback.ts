'use client';

import { useEffect } from 'react';
import { interaction, pointer } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { ring } from '@/scene/ringController';
import { getAudio } from '@/audio/AudioEngine';

/**
 * Pointer fallback.
 *
 * Hands are the primary input; this exists so the OS is never unusable. It
 * yields immediately the moment a hand appears — the two inputs never fight,
 * because the tracking loop owns `input` and this only claims it when the
 * pointer is the only thing moving.
 */
export function usePointerFallback() {
  useEffect(() => {
    const audio = getAudio();
    let spinning = false;
    let lastX = 0;

    const claim = () => {
      const s = useSystemStore.getState();
      if (s.tracking === 'active') return;
      if (s.input !== 'pointer') s.setInput('pointer');
    };

    const onMove = (e: PointerEvent) => {
      pointer.ndcX = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.ndcY = -((e.clientY / window.innerHeight) * 2 - 1);
      pointer.active = true;
      pointer.lastMove = performance.now();
      claim();

      if (spinning) {
        // Dragging empty space spins the ring, one screen width ~ two slots.
        const dx = e.clientX - lastX;
        lastX = e.clientX;
        ring.spin((-dx / window.innerWidth) * 4.2);
      }
    };

    const onDown = (e: PointerEvent) => {
      pointer.down = true;
      claim();
      // Only start a spin when the press did not land on a card: the card's
      // own handler will have claimed the drag already.
      window.setTimeout(() => {
        if (useCarouselStore.getState().draggingId === null && pointer.down) {
          spinning = true;
          lastX = e.clientX;
        }
      }, 0);
    };

    const onUp = () => {
      pointer.down = false;
      if (spinning) {
        spinning = false;
        ring.release();
        audio.whoosh(ring.velocity > 0 ? 1 : -1, 0.7);
      }
      const cards = useCarouselStore.getState();
      if (cards.draggingId) cards.endDrag(cards.draggingId, false);
    };

    const onLeave = () => {
      pointer.active = false;
      pointer.down = false;
      spinning = false;
    };

    const onWheel = (e: WheelEvent) => {
      if (Math.abs(e.deltaY) < 6 && Math.abs(e.deltaX) < 6) return;
      claim();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      ring.rotate(delta > 0 ? 1 : -1, 0.85);
      audio.whoosh(delta > 0 ? -1 : 1, 0.6);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    window.addEventListener('pointerup', onUp, { passive: true });
    window.addEventListener('pointercancel', onLeave, { passive: true });
    window.addEventListener('pointerleave', onLeave, { passive: true });
    window.addEventListener('wheel', onWheel, { passive: true });

    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onLeave);
      window.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('wheel', onWheel);
      interaction.grabbedId = null;
    };
  }, []);
}
