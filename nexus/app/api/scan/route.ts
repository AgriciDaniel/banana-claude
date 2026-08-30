import type { NextRequest } from "next/server";
import { scanChannels } from "@/server/providers/youtube";

/**
 * Development probe for the channel scan.
 *
 * The scan is otherwise only reachable through the assistant's tool loop,
 * which means testing it depends on the model being available -- and a
 * measurement path should not be untestable because someone else's service is
 * busy. This calls it directly with a theme and returns what came back.
 *
 * Closed in production: it costs real API quota per request and nothing in the
 * shipped interface has any business calling it.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (process.env.NODE_ENV === "production") {
    return new Response("Not found", { status: 404 });
  }

  const theme = request.nextUrl.searchParams.get("theme");
  if (!theme) return Response.json({ error: "theme is required" }, { status: 400 });

  const raw = Number(request.nextUrl.searchParams.get("limit"));
  const limit = Number.isFinite(raw) ? Math.min(8, Math.max(3, raw)) : 6;

  try {
    const channels = await scanChannels(theme, request.signal, limit);
    return Response.json({ theme, count: channels.length, channels });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 502 },
    );
  }
}
