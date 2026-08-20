import type { NextRequest } from "next/server";
import { findFacts } from "@/server/facts";
import { findPhoto } from "@/server/photo";

/**
 * Development probe for subject lookup.
 *
 * Same reasoning as the scan probe: this path is otherwise only reachable
 * through the assistant's tool loop, and a lookup should not be untestable
 * because someone else's model is busy. Closed in production, where nothing in
 * the interface has any business calling it.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (process.env.NODE_ENV === "production") {
    return new Response("Not found", { status: 404 });
  }

  const subject = request.nextUrl.searchParams.get("subject");
  if (!subject) return Response.json({ error: "subject is required" }, { status: 400 });

  try {
    const [photo, facts] = await Promise.all([
      findPhoto(subject, request.signal).catch(() => null),
      findFacts(subject, request.signal).catch(() => null),
    ]);
    return Response.json({ subject, photo, facts });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 502 },
    );
  }
}
