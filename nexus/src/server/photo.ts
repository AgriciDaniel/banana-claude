/**
 * Finding a real photograph of a real subject.
 *
 * The model can describe the picture it wants perfectly well, and it will
 * happily produce a Wikimedia URL to go with it -- but the path on that CDN is
 * a content hash, and a hash cannot be recalled, only looked up. So the URLs
 * came back plausible and dead: two different guesses at a photograph of the
 * same footballer, both 404.
 *
 * Wikipedia's summary endpoint answers with the real one. No key, no quota
 * worth counting, and the address comes from an API rather than from memory.
 */

const LANGUAGES = ['fr', 'en'] as const;

export interface FoundPhoto {
  url: string;
  title: string;
  description?: string;
  source: string;
}

interface Summary {
  title?: string;
  description?: string;
  originalimage?: { source?: string; width?: number };
  thumbnail?: { source?: string };
  type?: string;
}

/** Search a wiki for the page most likely to be the subject. */
async function resolveTitle(
  lang: string,
  subject: string,
  signal: AbortSignal,
): Promise<string | null> {
  const url =
    `https://${lang}.wikipedia.org/w/api.php?action=query&list=search&format=json` +
    `&srlimit=1&srsearch=${encodeURIComponent(subject)}&origin=*`;
  const response = await fetch(url, { signal, headers: { accept: 'application/json' } });
  if (!response.ok) return null;
  const data = (await response.json()) as {
    query?: { search?: Array<{ title?: string }> };
  };
  return data.query?.search?.[0]?.title ?? null;
}

export async function findPhoto(
  subject: string,
  signal: AbortSignal,
): Promise<FoundPhoto | null> {
  const query = subject.trim();
  if (!query) return null;

  for (const lang of LANGUAGES) {
    const title = await resolveTitle(lang, query, signal);
    if (!title) continue;

    const response = await fetch(
      `https://${lang}.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(title)}`,
      { signal, headers: { accept: 'application/json' } },
    );
    if (!response.ok) continue;

    const summary = (await response.json()) as Summary;
    /*
     * `originalimage` is the full-resolution file and `thumbnail` a scaled
     * one. The thumbnail is preferred when the original is enormous, since a
     * six-megapixel press photo is a slow download for a panel two metres
     * wide, but either is a genuine address.
     */
    const original = summary.originalimage;
    const url =
      original?.source && (original.width ?? 0) <= 2000
        ? original.source
        : (summary.thumbnail?.source ?? original?.source);

    if (!url) continue;

    return {
      url,
      title: summary.title ?? title,
      description: summary.description,
      source: `Wikipedia ${lang.toUpperCase()}`,
    };
  }

  return null;
}
