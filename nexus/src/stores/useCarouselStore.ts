'use client';

import { create } from 'zustand';
import type { CardState } from '@/core/types';
import { MODULES, MODULE_COUNT } from '@/config/modules';

/**
 * Discrete interaction state only. The ring's angle and momentum live in
 * `runtime.carousel` — putting them here would re-render the tree at 60 fps.
 */
interface CarouselState {
  /** Slot index nearest the viewer; mirrored from the runtime on settle. */
  focusedIndex: number;
  hoveredId: string | null;
  selectedId: string | null;
  expandedId: string | null;
  draggingId: string | null;
  /** Cards released with momentum, still flying under physics. */
  freeIds: string[];
  /**
   * Multi-selection, from the two-handed select gesture. Separate from
   * `selectedId` because one is "the card I am working on" and this is "the
   * set I have marked" - collapsing them would make either one unusable.
   */
  markedIds: string[];

  setFocusedIndex: (i: number) => void;
  setHovered: (id: string | null) => void;
  select: (id: string | null) => void;
  expand: (id: string | null) => void;
  collapse: () => void;
  beginDrag: (id: string) => void;
  endDrag: (id: string, free: boolean) => void;
  settle: (id: string) => void;
  setMultiSelection: (ids: string[]) => void;
  toggleMark: (id: string) => void;
  reset: () => void;
}

export const useCarouselStore = create<CarouselState>((set, get) => ({
  focusedIndex: 0,
  hoveredId: null,
  selectedId: null,
  expandedId: null,
  draggingId: null,
  freeIds: [],
  markedIds: [],

  setFocusedIndex: (focusedIndex) =>
    set({ focusedIndex: ((focusedIndex % MODULE_COUNT) + MODULE_COUNT) % MODULE_COUNT }),
  setHovered: (hoveredId) => set({ hoveredId }),
  select: (selectedId) => set({ selectedId }),
  expand: (expandedId) => set({ expandedId, selectedId: expandedId }),
  collapse: () => set({ expandedId: null }),
  beginDrag: (id) => set({ draggingId: id, selectedId: id }),
  endDrag: (id, free) =>
    set((s) => ({
      draggingId: s.draggingId === id ? null : s.draggingId,
      freeIds: free && !s.freeIds.includes(id) ? [...s.freeIds, id] : s.freeIds,
    })),
  settle: (id) => set((s) => ({ freeIds: s.freeIds.filter((f) => f !== id) })),
  setMultiSelection: (markedIds) => set({ markedIds }),
  toggleMark: (id) =>
    set((s) => ({
      markedIds: s.markedIds.includes(id)
        ? s.markedIds.filter((m) => m !== id)
        : [...s.markedIds, id],
    })),
  reset: () =>
    set({
      hoveredId: null,
      selectedId: null,
      expandedId: null,
      draggingId: null,
      freeIds: [],
      markedIds: [],
    }),
}));

/** Resolve the authoritative state of one card from the discrete store. */
export function resolveCardState(
  id: string,
  index: number,
  s: Pick<CarouselState, 'focusedIndex' | 'hoveredId' | 'selectedId' | 'expandedId' | 'draggingId'>,
): CardState {
  if (s.expandedId === id) return 'expanded';
  if (s.draggingId === id) return 'dragging';
  if (s.selectedId === id) return 'selected';
  if (s.focusedIndex === index) return 'focused';
  if (s.hoveredId === id) return 'hovered';
  return 'idle';
}

export const moduleIndexById = new Map(MODULES.map((m, i) => [m.id, i]));
