'use client';

import { create } from 'zustand';
import type { MediaItem } from '@/media/types';
import { bus } from './bus';

/**
 * What is currently on display in the room.
 *
 * A small stack rather than a single slot: showing a second chart should push
 * the first back rather than destroy it, so "and the other one" still works.
 * Three is the depth at which older frames read as a stack instead of clutter.
 *
 * The stack is scoped to a TOPIC, and that is the part worth understanding.
 * Without it, panels accumulated across a whole conversation: a chart drawn
 * for a question three subjects ago sat behind the current one, and dismissing
 * the front frame promoted that stale panel back to centre stage as though it
 * had just been asked for. Each new question opens a topic; when fresh media
 * arrives under it, everything from the previous topic stands down and leaves.
 *
 * Standing down happens on arrival, not on the question. A follow-up that
 * produces nothing new leaves what is on display alone, because the user is
 * probably still looking at it.
 */

const DEPTH = 3;
/** How long a retired frame takes to shrink away, in ms. */
export const RETIRE_MS = 900;

let counter = 0;

interface MediaState {
  /** Newest first. `stack[0]` is the focused frame. */
  stack: MediaItem[];
  /** Frames from a previous topic, on their way out. Never focusable. */
  retiring: MediaItem[];
  /** Incremented on every new question. */
  topic: number;
  /** True while a generation is in flight. */
  generating: boolean;
  error: string | null;

  show: (item: Omit<MediaItem, 'id' | 'at' | 'topic'>) => string;
  setAspect: (id: string, aspect: number) => void;
  dismiss: (id?: string) => void;
  clear: () => void;
  /** Open a new topic. Call when the user asks something. */
  beginTopic: () => void;
  setGenerating: (v: boolean) => void;
  setError: (message: string | null) => void;
}

export const useMediaStore = create<MediaState>((set, get) => ({
  stack: [],
  retiring: [],
  topic: 0,
  generating: false,
  error: null,

  show: (partial) => {
    const id = `m${++counter}`;
    const topic = get().topic;
    const item: MediaItem = { ...partial, id, at: Date.now(), topic };

    set((s) => {
      // Anything belonging to an earlier question steps aside now.
      const stale = s.stack.filter((m) => m.topic !== topic);
      const current = s.stack.filter((m) => m.topic === topic);
      return {
        stack: [item, ...current].slice(0, DEPTH),
        retiring: [...stale, ...s.retiring].slice(0, DEPTH),
        error: null,
      };
    });

    if (get().retiring.length > 0) {
      window.setTimeout(() => {
        set((s) => ({ retiring: s.retiring.filter((m) => m.topic === get().topic) }));
      }, RETIRE_MS);
    }

    bus.emit('media:show', { id, kind: item.kind });
    return id;
  },

  setAspect: (id, aspect) =>
    set((s) => ({
      stack: s.stack.map((item) => (item.id === id ? { ...item, aspect } : item)),
    })),

  /*
   * Dismissing the last frame of a topic takes the whole topic with it. The
   * alternative -- promoting whatever is underneath -- is what made a panel
   * from an earlier subject reappear unbidden.
   */
  dismiss: (id) =>
    set((s) => {
      const next = id ? s.stack.filter((item) => item.id !== id) : s.stack.slice(1);
      const front = next[0];
      if (front && front.topic !== s.topic) return { stack: [], retiring: next.slice(0, DEPTH) };
      return { stack: next };
    }),

  clear: () => set({ stack: [], retiring: [], error: null }),

  beginTopic: () => set((s) => ({ topic: s.topic + 1 })),

  setGenerating: (generating) => set({ generating }),
  setError: (error) => set({ error, generating: false }),
}));
