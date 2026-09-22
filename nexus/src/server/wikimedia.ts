/**
 * Shared access to the Wikimedia APIs.
 *
 * Two things they care about, and both bit us.
 *
 * They ask every client to identify itself with something descriptive and
 * contactable; an anonymous or generic agent gets a much shorter leash. And
 * they rate-limit hard: a subject lookup costs about five requests across
 * search, entity, labels and summary, so a handful of lookups in quick
 * succession earns a 429.
 *
 * A throttled request must not be reported as "nothing found" -- that is the
 * difference between "this person does not exist" and "ask me again in a
 * moment", and the assistant will say one or the other out loud.
 */

const AGENT =
  'NEXUS/1.0 (spatial computing environment; +https://github.com/AgriciDaniel/banana-claude)';

export class RateLimited extends Error {
  constructor() {
    super('Wikimedia is rate limiting this client; try again in a moment');
    this.name = 'RateLimited';
  }
}

const BACKOFF_MS = [400, 1200];

export async function wikiJson<T>(url: string, signal: AbortSignal): Promise<T | null> {
  for (let attempt = 0; ; attempt++) {
    const response = await fetch(url, {
      signal,
      headers: { accept: 'application/json', 'user-agent': AGENT },
    });

    if (response.ok) return (await response.json()) as T;

    if (response.status === 429 && attempt < BACKOFF_MS.length) {
      await new Promise((resolve) => setTimeout(resolve, BACKOFF_MS[attempt]));
      continue;
    }

    // Distinguished from a miss, because the caller must not call it a miss.
    if (response.status === 429) throw new RateLimited();
    return null;
  }
}
