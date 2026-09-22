import { getAudio } from '@/audio/AudioEngine';

/**
 * Speech output.
 *
 * Sentences are queued as the model produces them, so the assistant starts
 * talking while it is still thinking. Two backends behind one interface:
 *
 *   - `gemini`: PCM from /api/tts, decoded into Web Audio and played through
 *     the spatialised voice channel. High quality, positioned in the room.
 *   - `web`: the browser's SpeechSynthesis. Instant and free, but it writes
 *     straight to the output device, so it can be neither spatialised nor
 *     analysed for a real amplitude envelope.
 *
 * The backend is chosen once at prime() and degrades automatically: if a TTS
 * request fails mid-conversation the speaker falls back for the rest of the
 * session rather than going silent.
 */

export type VoiceBackend = 'gemini' | 'web' | 'none';

export interface SpeakerCallbacks {
  onStart: (text: string) => void;
  onEnd: () => void;
  /** Fires while audio plays; 0..1. */
  onLevel: (level: number) => void;
}

interface QueueItem {
  text: string;
  /** Prefetch promise for the gemini backend. */
  audio?: Promise<AudioBuffer | null>;
}

export class Speaker {
  private backend: VoiceBackend = 'none';
  private queue: QueueItem[] = [];
  private playing = false;
  private stopped = false;
  private finished = false;
  /** Incremented on every stop() so late async work can detect it is stale. */
  private generation = 0;

  private source: AudioBufferSourceNode | null = null;
  private utterance: SpeechSynthesisUtterance | null = null;
  private levelTimer = 0;
  private synthLevel = 0;

  constructor(private readonly callbacks: SpeakerCallbacks) {}

  get active(): boolean {
    return this.playing || this.queue.length > 0;
  }

  get mode(): VoiceBackend {
    return this.backend;
  }

  /** Decide which backend to use. Called once, after audio is unlocked. */
  async prime(preferGemini: boolean): Promise<VoiceBackend> {
    if (preferGemini && getAudio().voiceChannel()) {
      this.backend = 'gemini';
    } else if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      this.backend = 'web';
    } else {
      this.backend = 'none';
    }
    return this.backend;
  }

  /** Queue one sentence. Safe to call while earlier sentences are playing. */
  enqueue(text: string): void {
    const clean = text.trim();
    if (!clean || this.backend === 'none') return;
    this.stopped = false;

    const item: QueueItem = { text: clean };
    // Fetch the audio for this sentence NOW, while the previous one plays.
    // Without this the gap between sentences is a full network round trip.
    if (this.backend === 'gemini') item.audio = this.fetchAudio(clean, this.generation);
    this.queue.push(item);
    if (!this.playing) void this.drain();
  }

  /** No further sentences are coming for this turn. */
  finish(): void {
    this.finished = true;
    if (!this.playing && this.queue.length === 0) this.callbacks.onEnd();
  }

  /** Immediate silence. This is the barge-in path and must not await anything. */
  stop(): void {
    this.generation++;
    this.stopped = true;
    this.finished = false;
    this.queue.length = 0;

    if (this.source) {
      try {
        this.source.stop();
      } catch {
        /* already ended */
      }
      this.source.disconnect();
      this.source = null;
    }

    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    this.utterance = null;

    window.clearInterval(this.levelTimer);
    this.levelTimer = 0;
    this.synthLevel = 0;
    this.playing = false;
    this.callbacks.onLevel(0);
    getAudio().duck(0);
  }

  private async drain(): Promise<void> {
    if (this.playing) return;
    this.playing = true;

    while (this.queue.length > 0 && !this.stopped) {
      const item = this.queue.shift()!;
      this.callbacks.onStart(item.text);
      try {
        if (this.backend === 'gemini') await this.playBuffer(item);
        else await this.playSynth(item.text);
      } catch {
        /*
         * The good voice failed for this sentence -- a busy speech model
         * answers 429 and the route gives up after its retries. Dropping the
         * sentence made the assistant swallow a clause mid-answer, which reads
         * as a fault in the assistant rather than in a service. The browser's
         * own voice is worse, and it is far better than a gap.
         */
        if (this.backend === 'gemini' && !this.stopped) {
          try {
            await this.playSynth(item.text);
          } catch {
            // Neither voice is available; the queue still must not strand.
          }
        }
      }
    }

    this.playing = false;
    getAudio().duck(0);
    this.callbacks.onLevel(0);
    if (this.finished && !this.stopped) this.callbacks.onEnd();
  }

  private async playBuffer(item: QueueItem): Promise<void> {
    const generation = this.generation;
    const channel = getAudio().voiceChannel();
    const buffer = await (item.audio ?? this.fetchAudio(item.text, generation));

    if (this.stopped || generation !== this.generation) return;
    if (!buffer || !channel) {
      // Fall back permanently — one failure means the route is unavailable,
      // and silently saying nothing is the worst possible outcome.
      this.backend = 'web';
      await this.playSynth(item.text);
      return;
    }

    const source = channel.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(channel.input);
    this.source = source;

    getAudio().duck(1);
    this.startLevelPump();

    await new Promise<void>((resolve) => {
      source.onended = () => resolve();
      try {
        source.start();
      } catch {
        resolve();
      }
    });

    this.stopLevelPump();
    if (this.source === source) {
      source.disconnect();
      this.source = null;
    }
  }

  private async playSynth(text: string): Promise<void> {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    const generation = this.generation;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.04;
    utterance.pitch = 0.96;
    utterance.volume = 1;
    const voice = pickVoice(document.documentElement.lang || 'en');
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang ?? (document.documentElement.lang === 'fr' ? 'fr-FR' : 'en-US');
    this.utterance = utterance;

    getAudio().duck(1);
    // SpeechSynthesis gives no signal path to analyse, so the envelope is
    // synthesised from word boundaries. It is an approximation, and it is
    // honest about being one: it drives the glow, not a waveform display.
    this.startSynthEnvelope(utterance);

    await new Promise<void>((resolve) => {
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    });

    this.stopLevelPump();
    if (generation === this.generation) this.utterance = null;
  }

  /** POST one sentence to the TTS route and decode the PCM it returns. */
  private async fetchAudio(text: string, generation: number): Promise<AudioBuffer | null> {
    try {
      const res = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) return null;
      const body = (await res.json()) as { audio?: string; mimeType?: string };
      if (!body.audio || generation !== this.generation) return null;

      const channel = getAudio().voiceChannel();
      if (!channel) return null;
      return decodePcm(body.audio, body.mimeType ?? '', channel.ctx);
    } catch {
      return null;
    }
  }

  private startLevelPump(): void {
    window.clearInterval(this.levelTimer);
    this.levelTimer = window.setInterval(() => {
      this.callbacks.onLevel(getAudio().voiceLevel());
    }, 40);
  }

  private startSynthEnvelope(utterance: SpeechSynthesisUtterance): void {
    window.clearInterval(this.levelTimer);
    this.synthLevel = 0.5;
    utterance.onboundary = () => {
      this.synthLevel = 0.85;
    };
    this.levelTimer = window.setInterval(() => {
      // Decay between boundaries, with a little jitter so it never looks like
      // a metronome.
      this.synthLevel = Math.max(0.18, this.synthLevel * 0.82 + Math.random() * 0.06);
      this.callbacks.onLevel(this.synthLevel);
    }, 45);
  }

  private stopLevelPump(): void {
    window.clearInterval(this.levelTimer);
    this.levelTimer = 0;
    this.callbacks.onLevel(0);
  }
}

/** Prefer a natural-sounding local voice over the first one offered. */
function pickVoice(lang: string): SpeechSynthesisVoice | null {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return null;
  const wanted = lang.startsWith('fr') ? 'fr' : 'en';
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(wanted));
  if (voices.length === 0) return null;
  const preferred = voices.find((v) => /natural|neural|premium|enhanced|google/i.test(v.name));
  return preferred ?? voices[0]!;
}

/**
 * Gemini returns signed 16-bit little-endian PCM, sample rate in the mime type.
 * Web Audio has no decoder for headerless PCM, so it is converted by hand.
 */
function decodePcm(base64: string, mimeType: string, ctx: AudioContext): AudioBuffer | null {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const rateMatch = /rate=(\d+)/.exec(mimeType);
  const sampleRate = rateMatch ? Number(rateMatch[1]) : 24000;

  const samples = bytes.length >> 1;
  if (samples === 0) return null;

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const buffer = ctx.createBuffer(1, samples, sampleRate);
  const channel = buffer.getChannelData(0);
  for (let i = 0; i < samples; i++) {
    channel[i] = view.getInt16(i * 2, true) / 32768;
  }
  return buffer;
}
