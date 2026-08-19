import { getAssistant } from './AssistantEngine';
import { useAssistantStore, nextMessageId } from '@/stores/useAssistantStore';
import { executeCommand } from './commands';
import { bus } from '@/stores/bus';
import type { CommandCall } from './types';

/**
 * Development diagnostics surface.
 *
 * Exposed on `window.__nexus` in development only, and tree-shaken out of
 * production builds. Two reasons it earns its place:
 *
 *   - The holographic text is the hardest thing here to tune, and tuning it
 *     against the live API means paying for a model call every time you nudge
 *     a particle constant. `__nexus.simulate()` streams canned text through
 *     exactly the same path.
 *   - The assistant is unreachable without an API key, so without this there
 *     is no way to exercise the wake wave, the presence orb or the command
 *     executor on a fresh clone.
 */

export interface DevBridge {
  wake: () => void;
  sleep: () => void;
  ask: (text: string) => void;
  /** Stream text into the visuals at a realistic rate, with no API call. */
  simulate: (text: string, wordsPerSecond?: number) => void;
  /** Run a command exactly as the model would. */
  run: (name: string, args?: Record<string, unknown>) => void;
  state: () => ReturnType<typeof useAssistantStore.getState>;
}

let timer = 0;

export function installDevBridge(): () => void {
  if (process.env.NODE_ENV === 'production' || typeof window === 'undefined') {
    return () => {};
  }

  const bridge: DevBridge = {
    wake: () => getAssistant().wake('manual'),
    sleep: () => getAssistant().sleep('manual'),
    ask: (text) => void getAssistant().ask(text),

    simulate: (text, wordsPerSecond = 6) => {
      window.clearInterval(timer);
      const store = useAssistantStore.getState();
      store.setAwake(true);
      // Fire the real wake signal so the wave and the glow are exercised too,
      // not just the text.
      bus.emit('ai:wake', { source: 'manual' });
      store.pushUser('(simulated)');
      store.setStatus('streaming');

      const words = text.split(' ');
      let i = 0;
      timer = window.setInterval(() => {
        if (i >= words.length) {
          window.clearInterval(timer);
          useAssistantStore.getState().commitTurn({
            id: nextMessageId(),
            role: 'model',
            text,
            at: Date.now(),
          });
          useAssistantStore.getState().setStatus('listening');
          return;
        }
        useAssistantStore.getState().appendStream((i === 0 ? '' : ' ') + words[i]);
        i++;
      }, 1000 / wordsPerSecond);
    },

    run: (name, args = {}) => {
      executeCommand({ name, args } as CommandCall);
    },

    state: () => useAssistantStore.getState(),
  };

  (window as unknown as { __nexus: DevBridge }).__nexus = bridge;

  return () => {
    window.clearInterval(timer);
    delete (window as unknown as { __nexus?: DevBridge }).__nexus;
  };
}
