import type { NextRequest } from 'next/server';

/**
 * Speech synthesis.
 *
 * Returns raw PCM rather than an encoded file on purpose: the client decodes it
 * straight into an AudioBuffer and plays it through a PannerNode, which is what
 * lets the assistant's voice come from a point in the room. The browser's own
 * SpeechSynthesis cannot be routed through Web Audio at all, so it can never be
 * spatialised - it remains the fallback, not the target.
 *
 * One request per sentence. Speaking starts on the first sentence while the
 * model is still generating the rest.
 */

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API = 'https://generativelanguage.googleapis.com/v1beta/models';
const MODEL = process.env.GEMINI_TTS_MODEL ?? 'gemini-3.1-flash-tts-preview';
/** Kore is even and unhurried; the assistant should not sound excited. */
const VOICE = process.env.GEMINI_TTS_VOICE ?? 'Kore';
const ENABLED = process.env.GEMINI_TTS !== '0';

export async function GET() {
  return Response.json({
    available: Boolean(process.env.GEMINI_API_KEY) && ENABLED,
    model: MODEL,
    voice: VOICE,
  });
}

export async function POST(request: NextRequest) {
  const key = process.env.GEMINI_API_KEY;
  if (!key || !ENABLED) {
    return Response.json({ error: 'Gemini TTS disabled' }, { status: 503 });
  }

  let text: string;
  try {
    const body = (await request.json()) as { text?: string };
    text = (body.text ?? '').trim();
  } catch {
    return Response.json({ error: 'Malformed request body' }, { status: 400 });
  }
  if (!text) return Response.json({ error: 'Empty text' }, { status: 400 });
  // A sentence, not an essay. Guards against a runaway model turn becoming a
  // multi-megabyte audio request.
  if (text.length > 700) text = text.slice(0, 700);

  const body = JSON.stringify({
    contents: [{ parts: [{ text }] }],
    generationConfig: {
      responseModalities: ['AUDIO'],
      speechConfig: {
        voiceConfig: { prebuiltVoiceConfig: { voiceName: VOICE } },
      },
    },
  });

  /*
   * Speech is requested one sentence at a time, so a single bad roll does not
   * fail a request -- it silences a sentence in the middle of an answer, and
   * the user hears the assistant swallow a clause. The model answers a busy
   * moment with 429 or 503, both of which clear in well under a second, so
   * they are worth waiting out. Anything else is returned immediately.
   */
  const RETRY = new Set([429, 503]);
  const DELAYS = [350, 900];
  let upstream = await fetch(`${API}/${MODEL}:generateContent`, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
    body,
    signal: request.signal,
  });

  for (const delay of DELAYS) {
    if (!RETRY.has(upstream.status) || request.signal.aborted) break;
    await upstream.body?.cancel().catch(() => undefined);
    await new Promise((resolve) => setTimeout(resolve, delay));
    if (request.signal.aborted) break;
    upstream = await fetch(`${API}/${MODEL}:generateContent`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
      body,
      signal: request.signal,
    });
  }

  if (!upstream.ok) {
    const detail = await upstream.text().catch(() => '');
    return Response.json(
      { error: `TTS ${upstream.status}`, detail: detail.slice(0, 300) },
      { status: 502 },
    );
  }

  const payload = (await upstream.json()) as {
    candidates?: Array<{
      content?: { parts?: Array<{ inlineData?: { data?: string; mimeType?: string } }> };
    }>;
  };

  const inline = payload.candidates?.[0]?.content?.parts?.find((p) => p.inlineData)?.inlineData;
  if (!inline?.data) {
    return Response.json({ error: 'No audio returned' }, { status: 502 });
  }

  return Response.json({
    audio: inline.data,
    // e.g. "audio/L16;codec=pcm;rate=24000" — the client reads the rate out.
    mimeType: inline.mimeType ?? 'audio/L16;codec=pcm;rate=24000',
  });
}
