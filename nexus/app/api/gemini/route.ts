import type { NextRequest } from 'next/server';
import { COMMAND_DECLARATIONS } from '@/ai/commands';
import { buildSystemInstruction } from '@/ai/prompt';
import type { GenerateRequest } from '@/ai/types';

/**
 * Gemini streaming proxy.
 *
 * The API key stays on the server. This route re-emits Gemini's SSE as a
 * simpler line protocol, and it is the only file that knows Gemini exists -
 * swapping providers means editing this and nothing else.
 *
 * It also owns the FUNCTION-CALLING LOOP, which is the subtle part. A model
 * that calls a tool stops and waits for the result; if nobody sends one, the
 * turn ends silently. So: the route streams the call to the client (which
 * performs it against the live scene immediately), synthesises the tool
 * response itself, and continues the same turn on a second upstream request.
 * The user sees one continuous reply, and the interface has already moved.
 */

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API = 'https://generativelanguage.googleapis.com/v1beta/models';
/** Carriage return, spelled out: an escape here is one bad edit away from a
 *  literal newline in the source, which is exactly how this broke once. */
const CR = String.fromCharCode(13);
const EMPTY = '';

const MODEL = process.env.GEMINI_MODEL ?? 'gemini-3.7-flash';
/**
 * Search grounding is ON by default. Half the questions this assistant exists
 * to answer - "how is Nvidia today", "latest AI news", "what is the weather" -
 * are worthless without live data, and a confidently stale number is worse
 * than no number.
 */
const GROUNDING = process.env.GEMINI_GROUNDING !== '0';
/**
 * Gemini 3 deliberates before answering. For a voice assistant, time to first
 * spoken word beats depth, so thinking is off by default.
 */
const THINKING_BUDGET = Number(process.env.GEMINI_THINKING_BUDGET ?? '0');
/** Tool round trips per turn. Two is enough for "open X and tell me about it". */
const MAX_TOOL_DEPTH = 2;

interface GeminiPart {
  text?: string;
  /** Gemini 3 streams reasoning as parts flagged like this. Never shown. */
  thought?: boolean;
  /**
   * Gemini 3 REQUIRES this to be echoed back verbatim on the next request, or
   * it rejects the follow-up outright. It is opaque; do not touch it.
   */
  thoughtSignature?: string;
  functionCall?: { name: string; args?: Record<string, unknown>; id?: string };
}

interface GeminiCandidate {
  content?: { parts?: GeminiPart[]; role?: string };
  groundingMetadata?: { groundingChunks?: Array<{ web?: { title?: string; uri?: string } }> };
}

interface GeminiChunk {
  candidates?: GeminiCandidate[];
  error?: { message?: string };
}

type Content = { role: string; parts: unknown[] };
type Send = (payload: Record<string, unknown>) => void;

export async function GET() {
  // Cheap availability probe, so the client can say "offline" honestly rather
  // than failing on the user's first sentence.
  return Response.json({
    available: Boolean(process.env.GEMINI_API_KEY),
    model: MODEL,
    grounded: GROUNDING,
  });
}

export async function POST(request: NextRequest) {
  const key = process.env.GEMINI_API_KEY;
  if (!key) {
    return Response.json(
      { error: 'GEMINI_API_KEY is not set. Add it to .env.local and restart.' },
      { status: 503 },
    );
  }

  let body: GenerateRequest;
  try {
    body = (await request.json()) as GenerateRequest;
  } catch {
    return Response.json({ error: 'Malformed request body' }, { status: 400 });
  }

  const system = buildSystemInstruction(body.context, GROUNDING);
  const contents: Content[] = [
    ...body.history.map((m) => ({ role: m.role, parts: [{ text: m.text }] })),
    { role: 'user', parts: [{ text: body.prompt }] },
  ];

  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let closed = false;
      const send: Send = (payload) => {
        if (closed) return;
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`));
      };

      try {
        await runTurn(contents, 0, send, key, system, request.signal);
      } catch (error) {
        if (!request.signal.aborted) {
          send({ type: 'error', error: error instanceof Error ? error.message : String(error) });
        }
      }

      send({ type: 'done' });
      closed = true;
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-cache, no-transform',
      connection: 'keep-alive',
    },
  });
}

/** One upstream request. Recurses once per tool round trip. */
async function runTurn(
  contents: Content[],
  depth: number,
  send: Send,
  key: string,
  system: string,
  signal: AbortSignal,
): Promise<void> {
  const upstream = await callGemini(contents, key, system, signal, GROUNDING);

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => '');
    send({ type: 'error', error: extractError(detail) ?? `Gemini returned ${upstream.status}` });
    return;
  }

  /** The model's turn, kept verbatim so it can be replayed on the follow-up. */
  const modelParts: GeminiPart[] = [];
  const calls: Array<{ name: string; id?: string }> = [];
  let sentSources = false;

  await consume(upstream.body, (chunk) => {
    if (chunk.error?.message) {
      send({ type: 'error', error: chunk.error.message });
      return;
    }

    const candidate = chunk.candidates?.[0];
    for (const part of candidate?.content?.parts ?? []) {
      // Everything is retained for the replay, including reasoning parts and
      // the server-side search traffic - Gemini validates the whole turn.
      modelParts.push(part);

      // Reasoning is internal. Speaking it aloud would be wrong and unsettling.
      if (part.thought) continue;

      if (part.text) send({ type: 'text', text: part.text });

      if (part.functionCall) {
        calls.push({ name: part.functionCall.name, id: part.functionCall.id });
        send({
          type: 'command',
          command: { name: part.functionCall.name, args: part.functionCall.args ?? {} },
        });
      }
    }

    const grounding = candidate?.groundingMetadata?.groundingChunks;
    if (grounding?.length && !sentSources) {
      const sources = grounding
        .map((g) => ({ title: g.web?.title ?? '', uri: g.web?.uri ?? '' }))
        .filter((s) => s.uri);
      if (sources.length) {
        sentSources = true;
        send({ type: 'sources', sources: sources.slice(0, 4) });
      }
    }
  });

  if (calls.length === 0 || depth >= MAX_TOOL_DEPTH || signal.aborted) return;

  /*
   * The commands were dispatched to the client the moment they arrived and have
   * already been performed against the live scene. The route cannot observe
   * that outcome, so it reports the neutral truth - the call was delivered -
   * rather than inventing a result the model would then repeat to the user.
   */
  const responses = calls.map((call) => ({
    functionResponse: {
      name: call.name,
      ...(call.id ? { id: call.id } : {}),
      response: { status: 'dispatched to the interface' },
    },
  }));

  await runTurn(
    [...contents, { role: 'model', parts: modelParts }, { role: 'user', parts: responses }],
    depth + 1,
    send,
    key,
    system,
    signal,
  );
}

function callGemini(
  contents: Content[],
  key: string,
  system: string,
  signal: AbortSignal,
  grounded: boolean,
): Promise<Response> {
  const tools: unknown[] = [{ functionDeclarations: COMMAND_DECLARATIONS }];
  if (grounded) tools.push({ googleSearch: {} });

  return fetch(`${API}/${MODEL}:streamGenerateContent?alt=sse`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
    body: JSON.stringify({
      contents,
      systemInstruction: { parts: [{ text: system }] },
      tools,
      // Built-in tools (search) and our own functions may only be combined
      // when server-side tool invocations are explicitly opted into.
      ...(grounded ? { toolConfig: { includeServerSideToolInvocations: true } } : {}),
      generationConfig: {
        temperature: 0.75,
        topP: 0.95,
        maxOutputTokens: 1024,
        thinkingConfig: { thinkingBudget: THINKING_BUDGET },
      },
    }),
    signal,
  });
}

/** Read an SSE body and hand each decoded frame to `onChunk`. */
async function consume(
  body: ReadableStream<Uint8Array>,
  onChunk: (chunk: GeminiChunk) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = EMPTY;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      /*
       * Gemini terminates frames with CRLF CRLF, not LF LF. Searching for a
       * bare blank line therefore never matches and the whole stream silently
       * yields nothing - an assistant that connects fine and says absolutely
       * nothing. Strip carriage returns so there is only one case to handle.
       */
      buffer += decoder.decode(value, { stream: true }).split(CR).join(EMPTY);

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');

        const line = frame.split('\n').find((l) => l.startsWith('data:'));
        if (!line) continue;
        const json = line.slice(5).trim();
        if (!json || json === '[DONE]') continue;

        try {
          onChunk(JSON.parse(json) as GeminiChunk);
        } catch {
          /* a truncated frame is not worth killing the turn over */
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function extractError(raw: string): string | null {
  try {
    const parsed = JSON.parse(raw) as { error?: { message?: string } };
    return parsed.error?.message ?? null;
  } catch {
    return raw.slice(0, 200) || null;
  }
}
