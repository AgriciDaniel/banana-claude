import { getRecognitionCtor, type VoiceRecognition } from './speechTypes';

/**
 * Continuous speech recognition with wake-phrase gating and barge-in.
 *
 * Three problems this solves that a naive wrapper does not:
 *
 *   1. Chrome ends a recognition session on its own after a pause. Left alone
 *      the microphone silently dies after ~10 seconds. It is restarted, with
 *      backoff, until explicitly stopped.
 *   2. The assistant's own voice comes back through the microphone on speakers.
 *      Interim results are checked against what is currently being spoken, and
 *      an echo is discarded rather than being treated as an interruption.
 *   3. A wake phrase must be recognised mid-sentence, so the phrase is matched
 *      against interim results and the remainder of that same utterance is kept
 *      as the first command - "Nexus, open stocks" is one breath, not two.
 */

export type RecognizerPhase = 'idle' | 'listening' | 'error' | 'unsupported';

export interface RecognizerCallbacks {
  /** Wake phrase heard. `remainder` is anything said after it, possibly empty. */
  onWake: (remainder: string) => void;
  /** Interim or final transcript while awake. */
  onTranscript: (text: string, final: boolean) => void;
  /** A complete utterance while awake. */
  onUtterance: (text: string) => void;
  /** User spoke while the assistant was speaking. */
  onBargeIn: () => void;
  onPhase: (phase: RecognizerPhase, detail?: string) => void;
}

/** Matches "nexus", "hey nexus", and the things recognisers hear instead. */
const WAKE = /\b(hey\s+|ok\s+|hi\s+|salut\s+|dis\s+)?(nexus|nexis|nexsus|nexuse|next us|nexius)\b/i;

/** Ignore barge-in for this long after speech starts — the echo arrives first. */
const DEAF_MS = 320;
/**
 * Echo suppression stays armed this long AFTER the last sentence finishes.
 * Recognition lags the loudspeaker by several hundred milliseconds, so
 * disarming the moment playback ends lets the tail of the assistant's own
 * final sentence come back as a fresh question - which it then answers.
 */
const TAIL_MS = 1400;
/** A barge-in must be at least this many characters to count. */
const BARGE_MIN_CHARS = 3;

export class SpeechRecognizer {
  private recognition: VoiceRecognition | null = null;
  private running = false;
  private stopping = false;
  private restartDelay = 250;
  private restartTimer = 0;

  /**
   * Prefixes of everything spoken during the current utterance run, so echo
   * can be recognised and ignored. Accumulated across sentences because the
   * microphone hears a sentence slightly after we finish queueing the next.
   */
  private spokenPrefixes = new Set<string>();
  private speakingSince = 0;
  private speaking = false;
  /** Echo suppression remains active until this timestamp. */
  private echoArmedUntil = 0;
  private awake = false;
  private lastFinal = '';

  constructor(
    private readonly callbacks: RecognizerCallbacks,
    private lang = 'en-US',
  ) {}

  get supported(): boolean {
    return getRecognitionCtor() !== null;
  }

  setLanguage(tag: string): void {
    if (this.lang === tag) return;
    this.lang = tag;
    // The language is fixed at session start, so cycle to apply it.
    if (this.running) {
      this.restart(true);
    }
  }

  setAwake(awake: boolean): void {
    this.awake = awake;
  }

  /** Told by the speaker what is currently coming out of the loudspeakers. */
  setSpeaking(speaking: boolean, text = ''): void {
    this.speaking = speaking;
    if (speaking) {
      this.speakingSince = performance.now();
      this.echoArmedUntil = Infinity;
      for (const prefix of prefixes(text)) this.spokenPrefixes.add(prefix);
      // Bound the set so a long monologue cannot deafen the recogniser to a
      // genuine interruption that happens to reuse an early word.
      if (this.spokenPrefixes.size > 220) this.spokenPrefixes.clear();
    } else {
      // Keep the stems for the tail window rather than clearing immediately.
      this.echoArmedUntil = performance.now() + TAIL_MS;
    }
  }

  start(): void {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      this.callbacks.onPhase('unsupported');
      return;
    }
    if (this.running) return;

    this.stopping = false;
    const recognition = new Ctor();
    recognition.lang = this.lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      this.restartDelay = 250;
      this.callbacks.onPhase('listening');
    };

    recognition.onresult = (event) => this.handleResult(event.results, event.resultIndex);

    recognition.onerror = (event) => {
      // "no-speech" and "aborted" are routine; only real faults surface.
      if (event.error === 'no-speech' || event.error === 'aborted') return;
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        this.stopping = true;
        this.callbacks.onPhase('error', 'microphone permission denied');
        return;
      }
      this.callbacks.onPhase('error', event.error);
    };

    recognition.onend = () => {
      this.running = false;
      if (this.stopping) {
        this.callbacks.onPhase('idle');
        return;
      }
      // Backoff so a hard failure cannot become a restart loop.
      this.restartTimer = window.setTimeout(() => this.start(), this.restartDelay);
      this.restartDelay = Math.min(this.restartDelay * 1.6, 4000);
    };

    this.recognition = recognition;
    this.running = true;
    try {
      recognition.start();
    } catch {
      // start() throws if a session is already live; onend will recycle it.
      this.running = false;
    }
  }

  stop(): void {
    this.stopping = true;
    window.clearTimeout(this.restartTimer);
    this.running = false;
    try {
      this.recognition?.abort();
    } catch {
      /* already torn down */
    }
    this.recognition = null;
  }

  private restart(immediate = false): void {
    this.stop();
    this.stopping = false;
    if (immediate) this.start();
  }

  private handleResult(results: { length: number; [i: number]: { isFinal: boolean; [j: number]: { transcript: string } } }, from: number): void {
    let interim = '';
    let final = '';

    for (let i = from; i < results.length; i++) {
      const result = results[i];
      if (!result) continue;
      const text = result[0]?.transcript ?? '';
      if (result.isFinal) final += text;
      else interim += text;
    }

    const live = (final || interim).trim();
    if (!live) return;

    // --- barge-in and echo --------------------------------------------------
    const now = performance.now();
    if (now > this.echoArmedUntil && this.spokenPrefixes.size > 0) {
      this.spokenPrefixes.clear();
    }

    if (this.speaking || now <= this.echoArmedUntil) {
      if (this.isEcho(live)) return;
      // A genuine interruption, but only while audio is actually playing;
      // during the tail window there is nothing left to interrupt.
      if (this.speaking && now - this.speakingSince > DEAF_MS && live.length >= BARGE_MIN_CHARS) {
        this.callbacks.onBargeIn();
      }
    }

    // --- wake -------------------------------------------------------------
    if (!this.awake) {
      const match = WAKE.exec(live);
      if (!match) return;
      const remainder = live.slice(match.index + match[0].length).trim();
      // Wait for the final result before consuming a remainder, otherwise
      // "Nexus, open st..." fires with a truncated command.
      if (!final && remainder) {
        this.callbacks.onTranscript(live, false);
        return;
      }
      this.callbacks.onWake(remainder);
      return;
    }

    // --- normal dictation -------------------------------------------------
    this.callbacks.onTranscript(live, Boolean(final));
    if (final) {
      const text = final.trim();
      // Recognisers occasionally re-deliver the same final result.
      if (text && text !== this.lastFinal) {
        this.lastFinal = text;
        this.callbacks.onUtterance(text);
      }
    }
  }

  /**
   * Is this transcript just our own voice coming back?
   *
   * Compared on five-character stems rather than whole words. The recogniser
   * mangles what it hears, and when the assistant speaks English terms inside
   * a French reply the transcript comes back translated in spelling: "Model
   * Context Protocol" is heard as "modele contexte protocole". Whole-word
   * matching scores that at zero and treats the assistant's own voice as an
   * interruption, which is exactly what it did before this comment existed.
   * Stems match all three.
   */
  private isEcho(candidate: string): boolean {
    if (this.spokenPrefixes.size === 0) return false;
    const stems = prefixes(candidate);
    if (stems.length === 0) return true;
    let hits = 0;
    for (const stem of stems) if (this.spokenPrefixes.has(stem)) hits++;
    return hits / stems.length >= 0.45;
  }
}

/** Five-character stems of the meaningful words in a phrase. */
function prefixes(text: string): string[] {
  return normalise(text)
    .split(' ')
    .filter((w) => w.length > 2)
    .map((w) => w.slice(0, 5));
}

function normalise(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
