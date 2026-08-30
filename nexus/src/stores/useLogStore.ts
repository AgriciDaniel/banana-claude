'use client';

import { create } from 'zustand';

export type LogLevel = 'sys' | 'gesture' | 'ok' | 'warn';

export interface LogEntry {
  id: number;
  t: string;
  level: LogLevel;
  text: string;
}

const MAX = 7;
let counter = 0;

interface LogState {
  entries: LogEntry[];
  push: (level: LogLevel, text: string) => void;
  clear: () => void;
}

function stamp(): string {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0'))
    .join(':');
}

export const useLogStore = create<LogState>((set) => ({
  entries: [],
  push: (level, text) =>
    set((s) => {
      const last = s.entries[s.entries.length - 1];
      // Collapse identical consecutive lines instead of flooding the panel.
      if (last && last.text === text && last.level === level) return s;
      const entry: LogEntry = { id: ++counter, t: stamp(), level, text };
      const entries = [...s.entries, entry];
      return { entries: entries.length > MAX ? entries.slice(entries.length - MAX) : entries };
    }),
  clear: () => set({ entries: [] }),
}));

/** Imperative logger for non-React layers (gesture engine, physics, audio). */
export const log = {
  sys: (t: string) => useLogStore.getState().push('sys', t),
  gesture: (t: string) => useLogStore.getState().push('gesture', t),
  ok: (t: string) => useLogStore.getState().push('ok', t),
  warn: (t: string) => useLogStore.getState().push('warn', t),
};
