/**
 * Assistant contracts.
 *
 * Phase 2 adds a conversational layer on top of Phase 1. Nothing below this
 * directory knows the assistant exists: the ring, the cards, the gesture engine
 * and the physics layer are driven through the same public APIs a human hand
 * drives them through. That is the constraint the whole design defends.
 */

/**
 * The states the assistant can be in. Every one is visible to the user - an
 * assistant that is thinking and an assistant that is broken must never look
 * the same.
 */
export type AssistantStatus =
  | 'offline'
  | 'standby'
  | 'listening'
  | 'thinking'
  | 'streaming'
  | 'speaking'
  | 'interrupted';

export type MessageRole = 'user' | 'model';

export interface Message {
  id: string;
  role: MessageRole;
  text: string;
  at: number;
  /** Commands the model invoked while producing this turn. */
  commands?: string[];
  /** Grounding sources, when search grounding is enabled server-side. */
  sources?: { title: string; uri: string }[];
}

/** One function the model may call to drive the OS. */
export interface CommandCall {
  name: string;
  args: Record<string, unknown>;
}

/** Result of executing a command locally. */
export interface CommandResult {
  name: string;
  ok: boolean;
  /** Short human-readable outcome, surfaced in the log. */
  detail: string;
}

/** Everything the model is told about the current state of the OS. */
export interface SceneContext {
  /** Module currently front and centre. */
  focused: string | null;
  /** Module currently expanded, if any. This is what "this" refers to. */
  expanded: string | null;
  selected: string | null;
  frozen: boolean;
  locale: string;
  /** Ids the model is allowed to address. */
  modules: string[];
  localTime: string;
  /**
   * One line per module describing what it is currently showing. This is what
   * lets the assistant answer from the same numbers the user is looking at,
   * instead of going to the web and returning a different figure.
   */
  readings: string[];
  /**
   * Recommendations made in earlier sessions, with the figure as it stood at
   * the time. Lets the assistant re-adapt a plan instead of reissuing it.
   */
  proposals?: string[];
}

export interface StreamEvent {
  type: 'text' | 'command' | 'sources' | 'done' | 'error';
  text?: string;
  command?: CommandCall;
  sources?: { title: string; uri: string }[];
  error?: string;
}

/** Wire format for the /api/gemini route. */
export interface GenerateRequest {
  history: { role: MessageRole; text: string }[];
  prompt: string;
  context: SceneContext;
}
