'use client';

import { create } from 'zustand';
import type { MediaItem } from '@/media/types';
import { bus } from './bus';

/**
 * What is currently on display in the room.
 *
 * A small stack rather than a single slot: showing a second image should push
 * the first back rather than destroy it, so "show me the other one" and going
 * back are both possible. Three is the depth at which the older frames still
 * read as a stack instead of clutter.
 */

const DEPTH = 3;
let counter = 0;

interface MediaState {
  /** Newest first. `stack[0]` is the focused frame. */
  stack: MediaItem[];
  /** True while a generation is in flight. */
  generating: boolean;
  error: string | null;

  show: (item: Omit<MediaItem, 'id' | 'at'>) => string;
  setAspect: (id: string, aspect: number) => void;
  dismiss: (id?: string) => void;
  clear: () => void;
  setGenerating: (v: boolean) => void;
  setError: (message: string | null) => void;
}

export const useMediaStore = create<MediaState>((set) => ({
  stack: [],
  generating: false,
  error: null,

  show: (partial) => {
    const id = `m${++counter}`;
    const item: MediaItem = { ...partial, id, at: Date.now() };
    set((s) => ({ stack: [item, ...s.stack].slice(0, DEPTH), error: null }));
    bus.emit('media:show', { id, kind: item.kind });
    return id;
  },

  setAspect: (id, aspect) =>
    set((s) => ({
      stack: s.stack.map((item) => (item.id === id ? { ...item, aspect } : item)),
    })),

  dismiss: (id) =>
    set((s) => ({
      stack: id ? s.stack.filter((item) => item.id !== id) : s.stack.slice(1),
    })),

  clear: () => set({ stack: [], error: null }),
  setGenerating: (generating) => set({ generating }),
  setError: (error) => set({ error, generating: false }),
}));
