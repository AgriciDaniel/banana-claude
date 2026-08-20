import type { NextRequest } from 'next/server';
import type { ImagineRequest } from '@/media/types';

/**
 * Image generation.
 *
 * The assistant used to answer "I cannot display images in this environment".
 * It can now make one. Gemini returns the picture inline as base64, which is
 * handed straight to the browser as a data URI — no storage, no bucket, no
 * lifecycle to manage for something that exists as long as it is on screen.
 *
 * The response is a JSON envelope rather than raw bytes so a refusal or a
 * safety block arrives as a readable message instead of a broken image.
 */

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const API = 'https://generativelanguage.googleapis.com/v1beta/models';
/** Nano Banana 2. Fast enough that a floating panel does not feel stalled. */
const MODEL = process.env.GEMINI_IMAGE_MODEL ?? 'gemini-3.1-flash-image';
const TIMEOUT_MS = 60_000;

export async function GET() {
  return Response.json({ available: Boolean(process.env.GEMINI_API_KEY), model: MODEL });
}

export async function POST(request: NextRequest) {
  const key = process.env.GEMINI_API_KEY;
  if (!key) {
    return Response.json({ error: 'GEMINI_API_KEY is not set' }, { status: 503 });
  }

  let body: ImagineRequest;
  try {
    body = (await request.json()) as ImagineRequest;
  } catch {
    return Response.json({ error: 'Malformed request body' }, { status: 400 });
  }

  const prompt = (body.prompt ?? '').trim().slice(0, 900);
  if (!prompt) return Response.json({ error: 'Empty prompt' }, { status: 400 });

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  request.signal.addEventListener('abort', () => controller.abort());

  try {
    const upstream = await fetch(`${API}/${MODEL}:generateContent`, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({
        contents: [
          {
            role: 'user',
            parts: [
              {
                /*
                 * The panel floats in a dark volumetric room, so a subject on a
                 * dark ground composites into the scene instead of sitting in a
                 * bright rectangle stapled to it.
                 */
                text: `${prompt}\n\nComposition: single clear subject, dark background, cinematic rim lighting, no text, no watermark, no border.`,
              },
            ],
          },
        ],
        generationConfig: {
          responseModalities: ['IMAGE'],
          imageConfig: { imageSize: body.size ?? '1K' },
        },
      }),
    });

    if (!upstream.ok) {
      const detail = await upstream.text().catch(() => '');
      let message = `Image model returned ${upstream.status}`;
      try {
        message = (JSON.parse(detail) as { error?: { message?: string } }).error?.message ?? message;
      } catch {
        /* keep the status-based message */
      }
      return Response.json({ error: message }, { status: 502 });
    }

    const payload = (await upstream.json()) as {
      candidates?: Array<{
        content?: { parts?: Array<{ inlineData?: { data?: string; mimeType?: string } }> };
        finishReason?: string;
      }>;
    };

    const candidate = payload.candidates?.[0];
    const inline = candidate?.content?.parts?.find((p) => p.inlineData)?.inlineData;

    if (!inline?.data) {
      // A safety stop returns a candidate with no image and a reason worth showing.
      return Response.json(
        {
          error:
            candidate?.finishReason && candidate.finishReason !== 'STOP'
              ? `Image not produced (${candidate.finishReason})`
              : 'The model returned no image',
        },
        { status: 502 },
      );
    }

    return Response.json({
      src: `data:${inline.mimeType ?? 'image/jpeg'};base64,${inline.data}`,
      model: MODEL,
    });
  } catch (error) {
    const aborted = controller.signal.aborted && !request.signal.aborted;
    return Response.json(
      { error: aborted ? 'Image generation timed out' : String(error) },
      { status: 502 },
    );
  } finally {
    clearTimeout(timer);
  }
}
