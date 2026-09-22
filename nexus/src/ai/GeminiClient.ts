import type { GenerateRequest, StreamEvent } from './types';

const CR = String.fromCharCode(13);
const EMPTY = '';

/**
 * Streaming client.
 *
 * An async generator rather than a callback soup: the assistant engine can
 * `for await` over model output and stay readable, and cancellation is just an
 * AbortSignal. Everything provider-shaped lives behind /api/gemini, so this
 * file only knows about our own three event types.
 */

export interface Availability {
  available: boolean;
  model: string;
  grounded: boolean;
}

export async function probeAssistant(): Promise<Availability> {
  try {
    const res = await fetch('/api/gemini', { method: 'GET' });
    if (!res.ok) return { available: false, model: '', grounded: false };
    return (await res.json()) as Availability;
  } catch {
    return { available: false, model: '', grounded: false };
  }
}

export async function probeVoice(): Promise<boolean> {
  try {
    const res = await fetch('/api/tts', { method: 'GET' });
    if (!res.ok) return false;
    const body = (await res.json()) as { available?: boolean };
    return body.available === true;
  } catch {
    return false;
  }
}

export async function* streamGenerate(
  request: GenerateRequest,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  let response: Response;
  try {
    response = await fetch('/api/gemini', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    });
  } catch (err) {
    // An abort is a deliberate interruption, not a failure worth reporting.
    if (signal.aborted) return;
    yield { type: 'error', error: describe(err) };
    return;
  }

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}) as { error?: string });
    yield { type: 'error', error: detail.error ?? `Assistant returned ${response.status}` };
    return;
  }
  if (!response.body) {
    yield { type: 'error', error: 'Empty response stream' };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      // Stripped for the same reason the server route strips them: any proxy
      // between us may re-emit frames with CRLF terminators.
      buffer += decoder.decode(value, { stream: true }).split(CR).join(EMPTY);

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        if (!frame.startsWith('data:')) continue;
        const json = frame.slice(5).trim();
        if (!json) continue;
        try {
          yield JSON.parse(json) as StreamEvent;
        } catch {
          /* a truncated frame is not worth killing the turn over */
        }
      }
    }
  } catch (err) {
    if (!signal.aborted) yield { type: 'error', error: describe(err) };
  } finally {
    // Releasing the lock lets an aborted fetch tear its socket down promptly.
    reader.releaseLock();
  }
}

function describe(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === 'AbortError') return 'Interrupted';
    if (err.message.includes('fetch')) return 'Assistant unreachable';
    return err.message;
  }
  return String(err);
}
