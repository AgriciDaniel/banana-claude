import type { NextRequest } from "next/server";
import { SERVER_TOOL_DECLARATIONS, isServerTool, runServerTool } from "@/server/tools";
import { COMMAND_DECLARATIONS } from "@/ai/commands";
import { buildSystemInstruction } from "@/ai/prompt";
import type { GenerateRequest } from "@/ai/types";

/**
 * Gemini streaming proxy.
 *
 * The API key stays on the server. This route re-emits Gemini's SSE as a
 * simpler line protocol, and it is the only file that knows Gemini exists -
 * swapping providers means editing this and nothing else.
 *
 * It also owns the FUNCTION-CALLING LOOP, which is the subtle part. A model
 * that calls a tool stops and waits for the result; if nobody sends one, the
 * turn ends silently.
 *
 * Two kinds of call travel through it. Interface commands are streamed to the
 * client, which performs them against the live scene immediately; the route
 * cannot observe the outcome, so it answers with the neutral truth that the
 * request was delivered. Server tools run here instead, and their real output
 * goes back into the conversation - which is what lets the model reason about
 * figures it did not invent. Either way the user sees one continuous reply.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API = "https://generativelanguage.googleapis.com/v1beta/models";
/** Carriage return, spelled out: an escape here is one bad edit away from a
 *  literal newline in the source, which is exactly how this broke once. */
const CR = String.fromCharCode(13);
const EMPTY = "";

const MODEL = process.env.GEMINI_MODEL ?? "gemini-3.7-flash";
/**
 * Where a saturated primary goes. One version behind, and verified to serve
 * the grounded streaming shape that the newest model was refusing.
 */
const FALLBACK_MODEL = process.env.GEMINI_FALLBACK_MODEL ?? "gemini-3.6-flash";
/**
 * Search grounding is ON by default. Half the questions this assistant exists
 * to answer - "how is Nvidia today", "latest AI news", "what is the weather" -
 * are worthless without live data, and a confidently stale number is worse
 * than no number.
 */
const GROUNDING = process.env.GEMINI_GROUNDING !== "0";
/**
 * Gemini 3 deliberates before answering. For a voice assistant, time to first
 * spoken word beats depth, so thinking is off by default.
 */
const THINKING_BUDGET = Number(process.env.GEMINI_THINKING_BUDGET ?? "0");
/*
 * Tool round trips per turn. An analysis legitimately chains several steps --
 * survey the competition, chart the figure, then say what to do about it -- so
 * the original two was too few. Four is the point where a loop has stopped
 * working towards an answer.
 */
const MAX_TOOL_DEPTH = 4;

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
  groundingMetadata?: {
    groundingChunks?: Array<{ web?: { title?: string; uri?: string } }>;
  };
}

interface GeminiChunk {
  candidates?: GeminiCandidate[];
  error?: { message?: string };
}

type Content = { role: string; parts: unknown[] };

/**
 * Which model this request settled on.
 *
 * Sticky for the whole exchange, deliberately. Gemini 3 requires the opaque
 * `thoughtSignature` from a model turn to be echoed back verbatim, and a
 * signature minted by one model is not valid for another -- so falling back
 * per call rather than per request produced a follow-up carrying the primary
 * model's signature to the fallback, which answers INVALID_ARGUMENT. Once a
 * conversation moves, it stays moved.
 */
interface Session {
  model: string;
  fellBack: boolean;
}
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
      { error: "GEMINI_API_KEY is not set. Add it to .env.local and restart." },
      { status: 503 },
    );
  }

  let body: GenerateRequest;
  try {
    body = (await request.json()) as GenerateRequest;
  } catch {
    return Response.json({ error: "Malformed request body" }, { status: 400 });
  }

  const system = buildSystemInstruction(body.context, GROUNDING);
  const contents: Content[] = [
    ...body.history.map((m) => ({ role: m.role, parts: [{ text: m.text }] })),
    { role: "user", parts: [{ text: body.prompt }] },
  ];

  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let closed = false;
      const send: Send = (payload) => {
        if (closed) return;
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify(payload)}\n\n`),
        );
      };

      try {
        const session: Session = { model: MODEL, fellBack: false };
        await runTurn(contents, 0, send, key, system, request.signal, session);
      } catch (error) {
        if (!request.signal.aborted) {
          send({
            type: "error",
            error: error instanceof Error ? error.message : String(error),
          });
        }
      }

      send({ type: "done" });
      closed = true;
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
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
  session: Session,
): Promise<void> {
  // Past the cap the model answers with words or not at all.
  const mayCallTools = depth < MAX_TOOL_DEPTH;
  const upstream = await callGemini(
    contents,
    key,
    system,
    signal,
    GROUNDING,
    mayCallTools,
    session,
    depth === 0,
  );

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => "");
    send({
      type: "error",
      error: extractError(detail) ?? `Gemini returned ${upstream.status}`,
    });
    return;
  }

  /** The model's turn, kept verbatim so it can be replayed on the follow-up. */
  const modelParts: GeminiPart[] = [];
  const calls: Array<{
    name: string;
    id?: string;
    args: Record<string, unknown>;
  }> = [];
  let sentSources = false;
  let sentAnything = false;
  let sawError = false;

  await consume(upstream.body, (chunk) => {
    if (chunk.error?.message) {
      sawError = true;
      send({ type: "error", error: chunk.error.message });
      return;
    }

    const candidate = chunk.candidates?.[0];
    for (const part of candidate?.content?.parts ?? []) {
      // Everything is retained for the replay, including reasoning parts and
      // the server-side search traffic - Gemini validates the whole turn.
      modelParts.push(part);

      // Reasoning is internal. Speaking it aloud would be wrong and unsettling.
      if (part.thought) continue;

      if (part.text) {
        sentAnything = true;
        send({ type: "text", text: part.text });
      }

      if (part.functionCall) {
        const { name, id, args } = part.functionCall;
        calls.push({ name, id, args: args ?? {} });
        // Server tools are not the interface's business; forwarding one would
        // make the browser log a failure for a command it cannot perform.
        if (!isServerTool(name)) {
          send({ type: "command", command: { name, args: args ?? {} } });
        }
      }
    }

    const grounding = candidate?.groundingMetadata?.groundingChunks;
    if (grounding?.length && !sentSources) {
      const sources = grounding
        .map((g) => ({ title: g.web?.title ?? "", uri: g.web?.uri ?? "" }))
        .filter((s) => s.uri);
      if (sources.length) {
        sentSources = true;
        send({ type: "sources", sources: sources.slice(0, 4) });
      }
    }
  });

  /*
   * A turn can finish having said nothing, called nothing and failed at
   * nothing: a model that spends its whole output budget thinking stops on
   * MAX_TOKENS with an empty message. Left alone that is forty seconds of
   * silence the user cannot distinguish from a hang, so it is reported as
   * what it is rather than swallowed.
   */
  if (!sentAnything && calls.length === 0 && !sawError && !signal.aborted) {
    send({
      type: "error",
      error: "The model returned an empty answer, most likely having spent its budget deliberating. Try asking again, or more narrowly.",
    });
    return;
  }

  if (calls.length === 0 || signal.aborted) return;

  /*
   * The commands were dispatched to the client the moment they arrived and have
   * already been performed against the live scene. The route cannot observe
   * that outcome, so it reports the neutral truth - the call was delivered -
   * rather than inventing a result the model would then repeat to the user.
   */
  const responses = await Promise.all(
    calls.map(async (call) => ({
      functionResponse: {
        name: call.name,
        ...(call.id ? { id: call.id } : {}),
        response: isServerTool(call.name)
          ? await runServerTool(call.name, call.args, signal)
          : { status: "dispatched to the interface" },
      },
    })),
  );

  /*
   * At the cap, take the functions away rather than simply stopping. A turn
   * that ends on a function call has performed an action and said nothing, so
   * the user watches the room change while the assistant stays mute. Denied
   * any tool, the model has no option left but to answer in words.
   */
  await runTurn(
    [
      ...contents,
      { role: "model", parts: modelParts },
      { role: "user", parts: responses },
    ],
    depth + 1,
    send,
    key,
    system,
    signal,
    session,
  );
}

async function callGemini(
  contents: Content[],
  key: string,
  system: string,
  signal: AbortSignal,
  grounded: boolean,
  mayCallTools: boolean,
  session: Session,
  /**
   * Only the opening turn may change model. After it, `contents` carries
   * thoughtSignatures minted by the model that produced them, and those are
   * opaque and model-specific -- replaying one to a different model is
   * answered with INVALID_ARGUMENT, which is a worse failure than the
   * saturation it was trying to route around.
   */
  mayFallBack: boolean,
): Promise<Response> {
  const tools: unknown[] = [];
  if (mayCallTools) {
    tools.push({
      functionDeclarations: [...COMMAND_DECLARATIONS, ...SERVER_TOOL_DECLARATIONS],
    });
  }
  if (grounded) tools.push({ googleSearch: {} });

  const send = (model: string) =>
    fetch(`${API}/${model}:streamGenerateContent?alt=sse`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
          contents,
          systemInstruction: { parts: [{ text: system }] },
          // An empty tools array is not the same as no tools, and the API
          // rejects it. The final turn may legitimately have neither.
          ...(tools.length > 0 ? { tools } : {}),
          // Built-in tools (search) and our own functions may only be combined
          // when server-side tool invocations are explicitly opted into.
          ...(grounded
            ? { toolConfig: { includeServerSideToolInvocations: true } }
            : {}),
        generationConfig: {
          temperature: 0.75,
          topP: 0.95,
          /*
           * Thinking is billed against the SAME budget as the answer, so a
           * model that thinks needs room to think AND speak. Leaving the
           * fallback on 1024 with thinking enabled produced a forty-second
           * request that emitted nothing at all: the model spent the whole
           * budget deliberating and finished on MAX_TOKENS with an empty
           * message.
           */
          maxOutputTokens: model === MODEL ? 1024 : 2048,
          /*
           * And not every model will let thinking be switched off at all --
           * gemini-3.6-flash answers 400 to a budget of zero. The fallback
           * therefore gets a small positive budget rather than none, which it
           * accepts, instead of the primary's zero which it does not.
           */
          thinkingConfig: {
            thinkingBudget:
              model === MODEL ? THINKING_BUDGET : Math.max(THINKING_BUDGET, 128),
          },
        },
      }),
      signal,
    });

  const primary = await withRetry(() => send(session.model), signal);
  if (
    !RETRY_STATUS.has(primary.status) ||
    !mayFallBack ||
    session.fellBack ||
    session.model === FALLBACK_MODEL
  ) {
    return primary;
  }

  /*
   * Capacity is not uniform across models OR across request shapes. Grounded
   * streaming on the newest flash model answered 503 for an afternoon while
   * the same model served function-calling and plain streaming perfectly, and
   * while an older flash model served grounded streaming without complaint.
   *
   * Retrying the same model harder cannot fix that, so once the retries are
   * spent the request moves to a model that is merely a version behind. A
   * slightly older answer beats "the assistant is unavailable".
   */
  await primary.body?.cancel().catch(() => undefined);
  const secondary = await withRetry(() => send(FALLBACK_MODEL), signal);
  if (secondary.ok) {
    session.model = FALLBACK_MODEL;
    session.fellBack = true;
  }
  return secondary;
}

/**
 * Gemini answers a burst of load with 429/503 and a body that reads
 * "experiencing high traffic". Those clear in well under a second, and a user
 * who just spoke should not be told the assistant is broken because the first
 * attempt landed badly. Anything else -- a bad key, a malformed request -- is
 * returned untouched, because retrying it would only delay the real error.
 */
const RETRY_STATUS = new Set([429, 503]);
const RETRY_DELAYS_MS = [400, 1100];

async function withRetry(
  attempt: () => Promise<Response>,
  signal: AbortSignal,
): Promise<Response> {
  let response = await attempt();
  for (const delay of RETRY_DELAYS_MS) {
    if (!RETRY_STATUS.has(response.status) || signal.aborted) return response;
    // The body is unread on a failed attempt; release it before trying again.
    await response.body?.cancel().catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, delay));
    if (signal.aborted) break;
    response = await attempt();
  }
  return response;
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

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf("\n\n");

        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const json = line.slice(5).trim();
        if (!json || json === "[DONE]") continue;

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
