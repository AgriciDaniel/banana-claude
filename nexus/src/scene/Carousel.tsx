'use client';

import { useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { MODULES } from '@/config/modules';
import { HoloCard } from './HoloCard';
import { ring } from './ringController';
import { useCarouselStore } from '@/stores/useCarouselStore';

/**
 * The ring of modules.
 *
 * Deliberately thin: it integrates the ring controller and renders one card
 * per module. Cards position themselves from the shared ring angle rather than
 * being nested inside a rotating group, because a card that has been thrown
 * needs to leave the ring's coordinate space entirely and come back to it.
 */
export function Carousel() {
  const setFocusedIndex = useCarouselStore((s) => s.setFocusedIndex);

  useFrame((_, delta) => {
    ring.update(delta > 0.05 ? 0.05 : delta);

    // Mirror the discrete slot into React state only when it actually changes.
    const store = useCarouselStore.getState();
    if (store.focusedIndex !== ring.targetIndex) setFocusedIndex(ring.targetIndex);
  });

  useEffect(() => () => ring.reset(), []);

  return (
    <group name="carousel">
      {MODULES.map((module, index) => (
        <HoloCard key={module.id} module={module} index={index} />
      ))}
    </group>
  );
}
