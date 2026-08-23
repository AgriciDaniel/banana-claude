import { getAssistant } from './AssistantEngine';
import { useAssistantStore, nextMessageId } from '@/stores/useAssistantStore';
import { executeCommand } from './commands';
import { bus } from '@/stores/bus';
import { gestureSnapshot, interaction } from '@/stores/runtime';
import { useMediaStore } from '@/stores/useMediaStore';
import { MODULES } from '@/config/modules';
import { useFeedStore } from '@/modules/store';
import { deriveFace } from '@/modules/faces';
import { figureReport } from '@/scene/avatar/report';
import { attention, voice } from '@/stores/runtime';
import { rehearse, SCENARIOS } from '@/gesture/devScenarios';
import {
  startRecording,
  takeRecording,
  recordingLabels,
  replayRecording,
  forgetRecording,
  type Recording,
} from '@/gesture/recorder';
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
  /** Current tracking readout: hands, posture, rate, latency. */
  gesture: () => GestureReadout;
  /** Replay a synthetic hand movement through the live tracking pipeline. */
  rehearse: (scenario: string) => Promise<boolean>;
  /** Names of every available rehearsal. */
  scenarios: () => string[];
  /** What is on display, and which question each panel belongs to. */
  media: () => {
    topic: number;
    stack: Array<{ title: string; topic: number }>;
    retiring: Array<{ title: string; topic: number }>;
  };
  /** Where the figure is standing, what it is turned toward, and how big it
   *  comes out on screen. The only way to tune its placement. */
  figure: () => typeof figureReport & { attention: typeof attention };
  /** What each ring card is currently painting, and on what evidence. */
  cards: () => Array<{
    id: string;
    feed: string;
    source: string;
    values: string[];
  }>;
  /** Capture live landmarks under a label, for tuning against a real hand. */
  record: (label: string, ms: number) => void;
  /** Retrieve a capture. */
  take: (label: string) => Recording | null;
  takes: () => string[];
  /** Replay a capture through the pipeline at its original cadence. */
  replay: (label: string) => Promise<number>;
  forget: (label: string) => void;
}

export interface GestureReadout {
  hands: number;
  posture: string;
  confidence: number;
  /** Inference-to-publish cost for the last frame, ms. */
  latency: number;
  /** Frames actually processed per second. */
  rate: number;
  lastEvent: string | null;
  freezeProgress: number;
  spread: number;
  twoHanded: boolean;
  /** Primary hand measurements, for diagnosing a detector that stays silent. */
  span: number;
  depthVelocity: number;
  pinch: number;
  openness: number;
  /** Filtered palm centre, normalised image coordinates. */
  palmX: number;
  palmY: number;
  /** Palm speed in normalised units per second. */
  palmSpeed: number;
}

let timer = 0;
let envelope = 0;

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
      window.clearInterval(envelope);
      const store = useAssistantStore.getState();
      // A simulated turn is still a turn: it opens a topic, or the display
      // would behave differently under simulation than in real use.
      useMediaStore.getState().beginTopic();
      store.setAwake(true);
      // Fire the real wake signal so the wave and the glow are exercised too,
      // not just the text.
      bus.emit('ai:wake', { source: 'manual' });
      store.pushUser('(simulated)');
      store.setStatus('speaking');

      /*
       * A speech envelope, so the visuals driven by the voice are exercised too.
       *
       * Simulation exists to tune what the assistant looks like without paying
       * for a model call, and the moment the figure's mouth was wired to the
       * real envelope, the mouth became the one visual simulation could not
       * reach. This is not lip sync -- it is a decaying spike per word, which is
       * the same shape the real envelope has at this resolution.
       */
      envelope = window.setInterval(() => {
        voice.level *= 0.78;
      }, 40);

      const words = text.split(' ');
      let i = 0;
      timer = window.setInterval(() => {
        if (i >= words.length) {
          window.clearInterval(timer);
          window.clearInterval(envelope);
          voice.level = 0;
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
        // Longer words are louder for longer, which is close enough to true.
        voice.level = Math.min(1, 0.45 + (words[i]?.length ?? 3) * 0.06);
        i++;
      }, 1000 / wordsPerSecond);
    },

    run: (name, args = {}) => {
      executeCommand({ name, args } as CommandCall);
    },

    state: () => useAssistantStore.getState(),

    gesture: () => ({
      hands: gestureSnapshot.hands.length,
      posture: gestureSnapshot.posture,
      confidence: gestureSnapshot.confidence,
      latency: gestureSnapshot.latency,
      rate: gestureSnapshot.rate,
      lastEvent: gestureSnapshot.lastEvent?.kind ?? null,
      freezeProgress: gestureSnapshot.freezeProgress,
      spread: interaction.spread,
      twoHanded: interaction.twoHanded,
      span: gestureSnapshot.primary?.span ?? 0,
      depthVelocity: gestureSnapshot.primary?.depthVelocity ?? 0,
      pinch: gestureSnapshot.primary?.pinch ?? 0,
      openness: gestureSnapshot.primary?.openness ?? 0,
      palmX: gestureSnapshot.primary?.palm.x ?? 0,
      palmY: gestureSnapshot.primary?.palm.y ?? 0,
      palmSpeed: gestureSnapshot.primary
        ? Math.hypot(gestureSnapshot.primary.velocity.x, gestureSnapshot.primary.velocity.y)
        : 0,
    }),

    rehearse: (scenario) => rehearse(scenario),
    scenarios: () => Object.keys(SCENARIOS),

    media: () => {
      const s = useMediaStore.getState();
      const brief = (m: { title?: string; kind: string; topic: number }) => ({
        title: m.title ?? m.kind,
        topic: m.topic,
      });
      return { topic: s.topic, stack: s.stack.map(brief), retiring: s.retiring.map(brief) };
    },
    figure: () => ({ ...figureReport, attention: { ...attention } }),
    cards: () => {
      const feeds = useFeedStore.getState().feeds;
      return MODULES.map((mod) => {
        const feed = feeds[mod.id];
        const face = deriveFace(mod, feed);
        return {
          id: mod.id,
          feed: feed?.status ?? 'none',
          source: face.source,
          values: face.metrics.map((m) => `${m.label} ${m.value}`),
        };
      });
    },
    record: (label, ms) => startRecording(label, ms),
    take: (label) => takeRecording(label),
    takes: () => recordingLabels(),
    replay: (label) => replayRecording(label),
    forget: (label) => forgetRecording(label),
  };

  (window as unknown as { __nexus: DevBridge }).__nexus = bridge;

  return () => {
    window.clearInterval(timer);
    delete (window as unknown as { __nexus?: DevBridge }).__nexus;
  };
}
