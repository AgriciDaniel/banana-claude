import type { Article, ModuleFeed, NewsData } from '@/modules/types';

/**
 * News, from RSS.
 *
 * RSS needs no key, no quota and no terms negotiation, and every serious
 * publisher still ships it. Feeds are fetched in parallel, interleaved by
 * recency, and optionally digested by Gemini into a few spoken sentences.
 *
 * The parser is deliberately small and tolerant rather than a full XML stack:
 * feeds in the wild are malformed often enough that strictness is a liability.
 */

const DEFAULT_FEEDS = [
  'https://www.theverge.com/rss/index.xml',
  'https://feeds.arstechnica.com/arstechnica/technology-lab',
  'https://hnrss.org/frontpage?points=150',
  'https://www.wired.com/feed/tag/ai/latest/rss',
];

function feeds(): string[] {
  const custom = process.env.NEXUS_NEWS_FEEDS;
  if (!custom) return DEFAULT_FEEDS;
  const list = custom.split(',').map((s) => s.trim()).filter(Boolean);
  return list.length ? list : DEFAULT_FEEDS;
}

const decodeEntities = (text: string): string =>
  text
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&');

const stripTags = (html: string): string => decodeEntities(html.replace(/<[^>]+>/g, ' ')).replace(/\s+/g, ' ').trim();

function tag(block: string, name: string): string | null {
  /*
   * `[^]` rather than `[\s\S]`: this pattern is built as a template string,
   * where a lone backslash escape is silently swallowed by the JS parser and
   * the character class quietly degrades to "the letters s and S". `[^]` means
   * "any character including newlines" and survives any amount of escaping.
   */
  const match = new RegExp(`<${name}[^>]*>([^]*?)</${name}>`, 'i').exec(block);
  return match ? decodeEntities(match[1]!).trim() : null;
}

/** Atom puts the URL in an attribute; RSS puts it in the element body. */
function linkOf(block: string): string {
  const href = /<link[^>]+href=["']([^"']+)["']/i.exec(block);
  if (href) return href[1]!;
  return tag(block, 'link') ?? '';
}

function parseFeed(xml: string, fallbackSource: string): Article[] {
  const channelTitle = tag(xml.slice(0, 4000), 'title') ?? fallbackSource;
  const blocks = xml.match(/<(item|entry)[\s\S]*?<\/(item|entry)>/gi) ?? [];

  return blocks.slice(0, 12).flatMap((block) => {
    const title = tag(block, 'title');
    if (!title) return [];
    const link = linkOf(block);
    const rawSummary =
      tag(block, 'description') ?? tag(block, 'summary') ?? tag(block, 'content') ?? '';
    const dateText =
      tag(block, 'pubDate') ?? tag(block, 'published') ?? tag(block, 'updated') ?? '';
    const published = dateText ? Date.parse(dateText) : Date.now();

    return [
      {
        id: link || title,
        title: stripTags(title),
        summary: stripTags(rawSummary).slice(0, 320),
        source: stripTags(channelTitle).slice(0, 40),
        link,
        published: Number.isFinite(published) ? published : Date.now(),
      } satisfies Article,
    ];
  });
}

async function digest(articles: Article[], signal: AbortSignal): Promise<string | null> {
  const key = process.env.GEMINI_API_KEY;
  if (!key || articles.length === 0) return null;

  const model = process.env.GEMINI_MODEL ?? 'gemini-3.7-flash';
  const headlines = articles.slice(0, 12).map((a, i) => `${i + 1}. ${a.title} (${a.source})`).join('\n');

  try {
    const response = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`,
      {
        method: 'POST',
        signal,
        headers: { 'content-type': 'application/json', 'x-goog-api-key': key },
        body: JSON.stringify({
          contents: [
            {
              role: 'user',
              parts: [
                {
                  text:
                    'Here are current headlines. Write three sentences of plain prose telling me what actually matters today and why. No lists, no markdown, no preamble.\n\n' +
                    headlines,
                },
              ],
            },
          ],
          generationConfig: { temperature: 0.6, maxOutputTokens: 300, thinkingConfig: { thinkingBudget: 0 } },
        }),
      },
    );
    if (!response.ok) return null;
    const body = (await response.json()) as {
      candidates?: Array<{ content?: { parts?: Array<{ text?: string; thought?: boolean }> } }>;
    };
    const text = body.candidates?.[0]?.content?.parts
      ?.filter((p) => !p.thought && p.text)
      .map((p) => p.text)
      .join('')
      .trim();
    return text || null;
  } catch {
    return null;
  }
}

export async function fetchNews(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<NewsData>> {
  const sources = feeds();
  const results = await Promise.all(
    sources.map(async (url) => {
      try {
        const response = await fetch(url, {
          signal,
          headers: { 'user-agent': 'Mozilla/5.0 (compatible; NEXUS/1.0)' },
          next: { revalidate: 600 },
        });
        if (!response.ok) return [];
        return parseFeed(await response.text(), new URL(url).hostname);
      } catch {
        return [];
      }
    }),
  );

  const articles = results
    .flat()
    .sort((a, b) => b.published - a.published)
    .slice(0, 18);

  if (articles.length === 0) throw new Error('No feed returned any articles');

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: `RSS · ${sources.length} feeds`,
    data: { articles, digest: await digest(articles, signal) },
  };
}
