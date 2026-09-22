'use client';

import { create } from 'zustand';
import type { AssistantStatus, Message } from '@/ai/types';
import { bus } from './bus';

/**
 * Assistant state.
 *
 * Discrete only, following the Phase 1 rule: the streamed token text lives here
 * because it changes at reading speed (a few times a second), not at frame
 * rate. The speech amplitude envelope, which DOES change every frame, stays on
 * the runtime bus instead.
 */

const MAX_HISTORY = 24;
let seq = 0;

interface AssistantState {
  status: AssistantStatus;
  /** True between wake and sleep — the whole interface responds to this. */
  awake: boolean;
  /** Live recognition transcript, including interim results. */
  transcript: string;
  /** Whether `transcript` is final or still being revised. */
  transcriptFinal: boolean;
  /** Text streamed from the model so far for the current turn. */
  streaming: string;
  history: Message[];
  error: string | null;
  /** Set when no API key is configured — the assistant is inert but honest. */
  available: boolean;
  /** Speech recognition is supported by this browser. */
  micSupported: boolean;
  /** Which TTS backend actually ended up being used. */
  voice: 'gemini' | 'web' | 'none';

  setStatus: (status: AssistantStatus) => void;
  setAwake: (awake: boolean) => void;
  setTranscript: (text: string, final: boolean) => void;
  appendStream: (chunk: string) => void;
  commitTurn: (message: Message) => void;
  pushUser: (text: string) => void;
  setError: (error: string | null) => void;
  setAvailable: (available: boolean) => void;
  setMicSupported: (supported: boolean) => void;
  setVoice: (voice: 'gemini' | 'web' | 'none') => void;
  clear: () => void;
}

export const useAssistantStore = create<AssistantState>((set, get) => ({
  status: 'offline',
  awake: false,
  transcript: '',
  transcriptFinal: true,
  streaming: '',
  history: [],
  error: null,
  available: false,
  micSupported: false,
  voice: 'none',

  setStatus: (status) => {
    const previous = get().status;
    if (previous === status) return;
    set({ status });
    // Broadcast rather than let every consumer subscribe to the store: the
    // scene reacts to status without re-rendering on transcript changes.
    bus.emit('ai:status', { status, previous });
  },
  setAwake: (awake) => set({ awake }),
  setTranscript: (transcript, transcriptFinal) => set({ transcript, transcriptFinal }),
  appendStream: (chunk) => set((s) => ({ streaming: s.streaming + chunk })),
  commitTurn: (message) =>
    set((s) => {
      const history = [...s.history, message];
      return {
        history: history.length > MAX_HISTORY ? history.slice(-MAX_HISTORY) : history,
        streaming: '',
      };
    }),
  pushUser: (text) =>
    set((s) => {
      const message: Message = { id: `u${++seq}`, role: 'user', text, at: Date.now() };
      const history = [...s.history, message];
      return {
        history: history.length > MAX_HISTORY ? history.slice(-MAX_HISTORY) : history,
        streaming: '',
      };
    }),
  setError: (error) => set({ error }),
  setAvailable: (available) => set({ available }),
  setMicSupported: (micSupported) => set({ micSupported }),
  setVoice: (voice) => set({ voice }),
  clear: () => set({ history: [], streaming: '', transcript: '', error: null }),
}));

export const nextMessageId = () => `m${++seq}`;
