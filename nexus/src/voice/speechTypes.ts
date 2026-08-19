/**
 * Minimal ambient shapes for the Web Speech API.
 *
 * Deliberately NOT named `SpeechRecognition` etc. TypeScript's DOM library has
 * gained and lost these declarations across versions, so borrowing the names
 * makes the build depend on which lib.dom happens to be installed. Distinct
 * names plus one cast at the constructor is stable across all of them.
 */

export interface VoiceAlternative {
  transcript: string;
  confidence: number;
}

export interface VoiceResult {
  readonly length: number;
  isFinal: boolean;
  [index: number]: VoiceAlternative;
}

export interface VoiceResultList {
  readonly length: number;
  [index: number]: VoiceResult;
}

export interface VoiceRecognitionEvent {
  resultIndex: number;
  results: VoiceResultList;
}

export interface VoiceErrorEvent {
  error: string;
  message?: string;
}

export interface VoiceRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: VoiceRecognitionEvent) => void) | null;
  onerror: ((event: VoiceErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

type VoiceRecognitionCtor = new () => VoiceRecognition;

/** Returns the constructor if this browser has one, otherwise null. */
export function getRecognitionCtor(): VoiceRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: VoiceRecognitionCtor;
    webkitSpeechRecognition?: VoiceRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}
