import type { NextRequest } from 'next/server';
import type { ModuleFeed } from '@/modules/types';
import { fetchWeather } from '@/server/providers/weather';
import { fetchStocks } from '@/server/providers/stocks';
import { fetchNews } from '@/server/providers/news';
import { fetchSports } from '@/server/providers/sports';
import { fetchProjects } from '@/server/providers/projects';
import { fetchCalendar } from '@/server/providers/calendar';
import { fetchInstagram } from '@/server/providers/instagram';
import { fetchYoutube } from '@/server/providers/youtube';

/**
 * One route for every server-backed module.
 *
 * A single entry point rather than seven near-identical files, because the
 * interesting behaviour - timeouts, error shaping, cache headers, the promise
 * that a failure never produces a half-rendered module - is identical for all
 * of them and should exist exactly once.
 *
 * System, Music and AI are absent on purpose: they are measured in the browser
 * or answered by the assistant, and a server round trip would only add latency.
 */

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

type Provider = (params: URLSearchParams, signal: AbortSignal) => Promise<ModuleFeed<unknown>>;

const PROVIDERS: Record<string, Provider> = {
  weather: fetchWeather,
  stocks: fetchStocks,
  news: fetchNews,
  sports: fetchSports,
  projects: fetchProjects,
  calendar: fetchCalendar,
  instagram: fetchInstagram,
  youtube: fetchYoutube,
};

/** No module may hold the interface waiting longer than this. */
const TIMEOUT_MS = 12000;

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const provider = PROVIDERS[id];

  if (!provider) {
    return Response.json({ error: `No provider for module "${id}"` }, { status: 404 });
  }

  // Chain the caller's abort to our own deadline, so a slow upstream cannot
  // pin a connection open after the user has already moved on.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const onAbort = () => controller.abort();
  request.signal.addEventListener('abort', onAbort);

  try {
    const feed = await provider(request.nextUrl.searchParams, controller.signal);
    return Response.json(feed, {
      headers: { 'cache-control': 'no-store' },
    });
  } catch (error) {
    const timedOut = controller.signal.aborted && !request.signal.aborted;
    const failure: ModuleFeed<never> = {
      status: 'error',
      data: null,
      error: timedOut
        ? `${id} timed out after ${TIMEOUT_MS / 1000}s`
        : error instanceof Error
          ? error.message
          : String(error),
      fetchedAt: Date.now(),
      source: id,
    };
    // 200 with an error-shaped body: this is a module's health, not the
    // request's. The client renders the fault inside the module.
    return Response.json(failure, { headers: { 'cache-control': 'no-store' } });
  } finally {
    clearTimeout(timer);
    request.signal.removeEventListener('abort', onAbort);
  }
}
