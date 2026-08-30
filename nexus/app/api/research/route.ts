import type { NextRequest } from "next/server";
import { findFacts } from "@/server/facts";
import { findPhoto } from "@/server/photo";
import { findMatches, matchPlayerStats } from "@/server/statsbomb";

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

  const params = request.nextUrl.searchParams;

  // The same probe covers the StatsBomb path, for the same reason.
  const matchId = params.get("match");
  if (matchId) {
    const stats = await matchPlayerStats(Number(matchId), request.signal);
    return Response.json(stats ?? { error: "no event data" });
  }
  const team = params.get("team");
  if (team) {
    const matches = await findMatches(
      { team, competition: params.get("competition") ?? undefined },
      request.signal,
    );
    return Response.json({ matches });
  }

  const subject = params.get("subject");
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
