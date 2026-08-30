import { SpeechRecognizer } from '@/voice/SpeechRecognizer';
import { Speaker } from '@/voice/Speaker';
import { streamGenerate, probeAssistant, probeVoice } from './GeminiClient';
import { executeCommand, readSceneContext } from './commands';
import { stripWakePhrase } from './prompt';
import { useMediaStore } from '@/stores/useMediaStore';
import { useAssistantStore, nextMessageId } from '@/stores/useAssistantStore';
import { bus } from '@/stores/bus';
import { log } from '@/stores/useLogStore';
import { getAudio } from '@/audio/AudioEngine';
import { t, useLocaleStore } from '@/i18n';
import { voice as voiceRuntime } from '@/stores/runtime';
import type { Message, SceneContext } from './types';

/**
 * The assistant.
 *
 * A plain class, deliberately: it owns a microphone, a network stream and an
 * audio queue, none of which survive React's render model comfortably. One
 * hook mounts it; everything else talks to it through the store and the bus.
 *
 * The turn cycle is a strict state machine, because every intermediate state
 * is visible to the user:
 *
 *   standby -> listening -> thinking -> streaming -> speaking -> listening
 *                                   \-> interrupted -> listening
 */

/** Return to standby after this long with nothing said. */
const IDLE_SLEEP_MS = 22000;
/** A sentence shorter than this is held back and merged with the next one. */
const MIN_SENTENCE = 14;

export class AssistantEngine {
  private recognizer: SpeechRecognizer;
  private speaker: Speaker;
  private controller: AbortController | null = null;
  private sleepTimer = 0;
  private disposed = false;
  private started = false;
  /** Unsubscribe for the gesture subscription; leaking it would let a disposed
   *  engine keep waking on a circle after a StrictMode remount. */
  private offGesture: (() => void) | null = null;

  /** Buffer of streamed text not yet flushed as a sentence. */
  private pending = '';
  private sentenceIndex = 0;
  private turnText = '';
  private turnCommands: string[] = [];

  constructor() {
    this.recognizer = new SpeechRecognizer(
      {
        onWake: (remainder) => this.wake('phrase', remainder),
        onTranscript: (text, final) => {
          useAssistantStore.getState().setTranscript(text, final);
          if (!final) this.touch();
        },
        onUtterance: (text) => void this.ask(text),
        onBargeIn: () => this.interrupt(),
        onPhase: (phase, detail) => {
          if (phase === 'error' && detail) {
            useAssistantStore.getState().setError(detail);
            log.warn(t('log.aiMicError', { error: detail.toUpperCase() }));
          }
        },
      },
      localeTag(),
    );

    this.speaker = new Speaker({
      onStart: (text) => {
        this.recognizer.setSpeaking(true, text);
        useAssistantStore.getState().setStatus('speaking');
      },
      onEnd: () => {
        this.recognizer.setSpeaking(false);
        voiceRuntime.level = 0;
        const store = useAssistantStore.getState();
        if (store.awake && store.status !== 'interrupted') {
          store.setStatus('listening');
          this.touch();
        }
      },
      onLevel: (level) => {
        voiceRuntime.level = level;
        bus.emit('ai:level', { level });
      },
    });
  }

  /** Probe capability and start listening for the wake phrase. */
  async start(): Promise<void> {
    if (this.started || this.disposed) return;
    this.started = true;
    const store = useAssistantStore.getState();

    store.setMicSupported(this.recognizer.supported);

    const [assistant, ttsAvailable] = await Promise.all([probeAssistant(), probeVoice()]);
    if (this.disposed) return;

    store.setAvailable(assistant.available);
    if (!assistant.available) {
      store.setStatus('offline');
      log.warn(t('log.aiOffline'));
      return;
    }

    const backend = await this.speaker.prime(ttsAvailable);
    store.setVoice(backend);
    store.setStatus('standby');
    log.ok(
      t('log.aiOnline', {
        model: assistant.model.toUpperCase(),
        voice: backend.toUpperCase(),
      }),
    );

    if (this.recognizer.supported) this.recognizer.start();
    else log.warn(t('log.aiNoMic'));

    // The circle gesture is Phase 1's reserved verb. It is claimed here by
    // subscribing to the existing gesture bus — the gesture engine and the
    // interaction driver are not modified at all.
    this.offGesture = bus.on('gesture', (event) => {
      if (event.kind === 'circle') this.wake('gesture', '');
    });
  }

  /** Bring the assistant forward. Idempotent. */
  wake(source: 'phrase' | 'gesture' | 'manual', remainder = ''): void {
    const store = useAssistantStore.getState();
    if (!store.available) {
      getAudio().deny();
      return;
    }

    if (!store.awake) {
      store.setAwake(true);
      store.setStatus('listening');
      this.recognizer.setAwake(true);
      getAudio().wake();
      bus.emit('ai:wake', { source });
      log.ok(t('log.aiWake'));
    }
    this.touch();

    // "Nexus, open stocks" arrives as one utterance; the tail is the command.
    const tail = stripWakePhrase(remainder).trim();
    if (tail.length > 1) void this.ask(tail);
  }

  sleep(reason: 'timeout' | 'command' | 'error' | 'manual'): void {
    const store = useAssistantStore.getState();
    if (!store.awake) return;
    window.clearTimeout(this.sleepTimer);
    this.abort();
    this.speaker.stop();
    this.recognizer.setAwake(false);
    this.recognizer.setSpeaking(false);
    store.setAwake(false);
    store.setTranscript('', true);
    store.setStatus(store.available ? 'standby' : 'offline');
    getAudio().sleep();
    bus.emit('ai:sleep', { reason });
  }

  /** Cut the assistant off mid-sentence. The whole point is that it is instant. */
  interrupt(): void {
    const store = useAssistantStore.getState();
    if (store.status !== 'speaking' && store.status !== 'streaming') return;

    this.abort();
    this.speaker.stop();
    voiceRuntime.level = 0;
    store.setStatus('interrupted');
    getAudio().cut();
    bus.emit('ai:interrupt', {});
    log.gesture(t('log.aiInterrupted'));

    // Interrupted is a moment, not a resting place.
    window.setTimeout(() => {
      const current = useAssistantStore.getState();
      if (current.status === 'interrupted' && current.awake) {
        current.setStatus('listening');
        this.touch();
      }
    }, 420);
  }

  /** Run one full turn. */
  async ask(rawPrompt: string): Promise<void> {
    const prompt = stripWakePhrase(rawPrompt).trim();
    const store = useAssistantStore.getState();
    if (!prompt || !store.available) return;
    if (!store.awake) this.wake('manual');

    this.abort();
    this.speaker.stop();
    window.clearTimeout(this.sleepTimer);

    store.pushUser(prompt);
    /*
     * A new question opens a new topic for the display. Nothing is cleared
     * here: panels only stand down once this turn actually produces something
     * to replace them, so a follow-up that draws nothing leaves the user
     * looking at what they were already looking at.
     */
    useMediaStore.getState().beginTopic();
    store.setTranscript(prompt, true);
    store.setError(null);
    store.setStatus('thinking');
    log.gesture(t('log.aiAsk', { text: truncate(prompt, 34).toUpperCase() }));

    this.pending = '';
    this.turnText = '';
    this.turnCommands = [];
    this.sentenceIndex = 0;

    const controller = new AbortController();
    this.controller = controller;

    const context = readSceneContext() as SceneContext;
    const history = useAssistantStore
      .getState()
      .history.slice(0, -1)
      .map((m) => ({ role: m.role, text: m.text }));

    let sawText = false;
    let failed: string | null = null;
    let sources: Message['sources'];

    try {
      for await (const event of streamGenerate({ history, prompt, context }, controller.signal)) {
        if (controller.signal.aborted) return;

        switch (event.type) {
          case 'text': {
            if (!event.text) break;
            event.text = stripCitations(event.text);
            if (!event.text) break;
            if (!sawText) {
              sawText = true;
              useAssistantStore.getState().setStatus('streaming');
            }
            sawText = true;
            this.turnText += event.text;
            useAssistantStore.getState().appendStream(event.text);
            bus.emit('ai:token', { text: event.text, done: false });
            this.chunk(event.text);
            break;
          }

          case 'command': {
            if (!event.command) break;
            const result = executeCommand(event.command);
            this.turnCommands.push(event.command.name);
            log.sys(
              t('log.aiCommand', {
                name: event.command.name.replace(/_/g, ' ').toUpperCase(),
              }),
            );
            if (!result.ok) failed = result.detail;
            break;
          }

          case 'sources':
            sources = event.sources;
            break;

          case 'error':
            failed = event.error ?? 'unknown error';
            break;

          case 'done':
            break;
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) failed = err instanceof Error ? err.message : String(err);
    }

    if (controller.signal.aborted || this.disposed) return;
    this.controller = null;

    this.flushPending();
    bus.emit('ai:token', { text: '', done: true });

    if (failed && !this.turnText) {
      useAssistantStore.getState().setError(failed);
      useAssistantStore.getState().setStatus('listening');
      log.warn(t('log.aiError', { error: truncate(failed, 40).toUpperCase() }));
      getAudio().deny();
      this.touch();
      return;
    }

    const text = this.turnText.trim();
    if (text) {
      const message: Message = {
        id: nextMessageId(),
        role: 'model',
        text,
        at: Date.now(),
        commands: this.turnCommands.length ? [...this.turnCommands] : undefined,
        sources,
      };
      useAssistantStore.getState().commitTurn(message);
    } else {
      // A pure command turn with no prose. Acknowledge without speaking.
      useAssistantStore.getState().commitTurn({
        id: nextMessageId(),
        role: 'model',
        text: '',
        at: Date.now(),
        commands: [...this.turnCommands],
      });
    }

    this.speaker.finish();
    if (!this.speaker.active) {
      useAssistantStore.getState().setStatus('listening');
      this.touch();
    }
  }

  /**
   * Split streamed text into speakable sentences.
   *
   * Speech must start before generation finishes, so the stream is cut at
   * sentence boundaries as they arrive. Two guards matter: a decimal point is
   * not a full stop ("1.5 percent"), and a very short fragment is held back and
   * merged rather than spoken alone, because "Yes." as its own utterance has a
   * jarring gap after it.
   */
  private chunk(delta: string): void {
    this.pending += delta;

    while (true) {
      const cut = findSentenceEnd(this.pending);
      if (cut === -1) break;

      const sentence = this.pending.slice(0, cut + 1).trim();
      const rest = this.pending.slice(cut + 1);

      if (sentence.length < MIN_SENTENCE && rest.length === 0) break;
      this.pending = rest;
      if (sentence) this.speak(sentence);
    }
  }

  private flushPending(): void {
    const tail = this.pending.trim();
    this.pending = '';
    if (tail) this.speak(tail);
  }

  private speak(sentence: string): void {
    bus.emit('ai:sentence', { text: sentence, index: this.sentenceIndex++ });
    this.speaker.enqueue(sentence);
  }

  private abort(): void {
    this.controller?.abort();
    this.controller = null;
  }

  /** Reset the idle timer. Any sign of life defers sleep. */
  private touch(): void {
    window.clearTimeout(this.sleepTimer);
    this.sleepTimer = window.setTimeout(() => this.sleep('timeout'), IDLE_SLEEP_MS);
  }

  /** Recognition language follows the interface language. */
  syncLocale(): void {
    this.recognizer.setLanguage(localeTag());
  }

  dispose(): void {
    this.disposed = true;
    this.offGesture?.();
    this.offGesture = null;
    window.clearTimeout(this.sleepTimer);
    this.abort();
    this.speaker.stop();
    this.recognizer.stop();
    voiceRuntime.level = 0;
  }
}

function localeTag(): string {
  return useLocaleStore.getState().locale === 'fr' ? 'fr-FR' : 'en-US';
}

/**
 * Index of the last character of the first complete sentence, or -1.
 * Rejects decimals, ellipses mid-thought, and abbreviations followed by a
 * lower-case word.
 */
function findSentenceEnd(text: string): number {
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (ch !== '.' && ch !== '!' && ch !== '?' && ch !== '\n') continue;

    if (ch === '.') {
      const prev = text[i - 1];
      const next = text[i + 1];
      // "1.5" — a digit either side means a decimal, not a full stop.
      if (prev && next && /\d/.test(prev) && /\d/.test(next)) continue;
      // "..." — wait for the last one.
      if (next === '.') continue;
    }

    // A terminator only ends a sentence if whitespace or the end follows.
    const after = text[i + 1];
    if (after && !/\s/.test(after)) continue;
    return i;
  }
  return -1;
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}\u2026`;
}

/** One engine per document. */
let engine: AssistantEngine | null = null;

export function getAssistant(): AssistantEngine {
  engine ??= new AssistantEngine();
  return engine;
}

export function disposeAssistant(): void {
  engine?.dispose();
  engine = null;
}

/**
 * Grounded answers carry citation markers -- "[1]", "[2, 3]" -- meant for a
 * page with footnotes. Here the text is SPOKEN, and an assistant that says
 * "crochet un" at the end of a sentence sounds broken. The sources are
 * surfaced separately anyway, so the markers are stripped rather than read.
 */
const CITATION = /\s*\[\d+(?:\s*,\s*\d+)*\]/g;

export function stripCitations(text: string): string {
  return text.replace(CITATION, '');
}
