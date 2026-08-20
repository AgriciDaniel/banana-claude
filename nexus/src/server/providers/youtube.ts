import type { ChannelBenchmark, ModuleFeed, YoutubeData, YoutubeVideo } from '@/modules/types';

/**
 * YouTube, through the public Data API.
 *
 * Deliberately key-only, no OAuth. Everything the interface needs about a
 * channel -- subscribers, views, the last uploads and how each performed -- is
 * public data, and demanding an OAuth dance to read your own public numbers
 * would put a consent screen between the user and a figure anyone can see.
 *
 * The same key also buys the thing that makes strategy possible here: the
 * ability to look at OTHER channels. A benchmark you cannot measure is an
 * opinion, so `scanChannels` below goes and gets real ones.
 */

const API = 'https://www.googleapis.com/youtube/v3';

function key(): string | null {
  const value = (process.env.YOUTUBE_API_KEY ?? '').trim();
  return value.length > 0 ? value : null;
}

/**
 * The "AQ." family: keys bound to a service account and restricted to the
 * Gemini and Vertex Agent Platform APIs. They are handed out by AI Studio and
 * by the Cloud console's Gemini flow alike, so the origin is no guide -- what
 * matters is that the restriction cannot be widened to cover YouTube.
 */
function isGeminiOnlyKey(value: string): boolean {
  return value.startsWith('AQ.');
}

/**
 * A Google API key is around thirty-nine characters. Anything much shorter is
 * a placeholder or a truncated paste, and it is worth naming as such because
 * of where those tend to come from: a variable already set in the shell or in
 * the user's system environment SHADOWS .env.local entirely under Next, so a
 * perfectly good key can be pasted into the file and never once be read. That
 * failure is invisible from inside the app unless something says it out loud.
 */
const PLAUSIBLE_KEY_LENGTH = 30;

function isTruncatedKey(value: string): boolean {
  return value.length < PLAUSIBLE_KEY_LENGTH;
}

const SHADOWED_HINT =
  'The YOUTUBE_API_KEY being read is too short to be a real key. Something is supplying a placeholder: check for a YOUTUBE_API_KEY already set in your shell or in your Windows user environment variables, because those take precedence over .env.local and a key pasted into the file will be ignored while one exists.';

const GEMINI_ONLY_HINT =
  'That key starts with "AQ.", which means it is tied to a service account and restricted to the Gemini and Vertex Agent Platform APIs. Its API restriction cannot be widened to YouTube, so enabling YouTube Data API v3 changes nothing for it. You need a plain API key: console.cloud.google.com, APIs and services, Credentials, Create credentials, API key - not linked to a service account, restricted to YouTube Data API v3. It will start with "AIza" and be about forty characters.';

async function api<T>(
  path: string,
  apiKey: string,
  signal: AbortSignal,
): Promise<T | null> {
  const response = await fetch(`${API}/${path}&key=${apiKey}`, {
    signal,
    headers: { accept: 'application/json' },
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');

    /*
     * Quota exhaustion is the failure users actually hit, and it looks
     * identical to a bad key unless the body is read. Ten thousand units a day
     * sounds generous until a search costs a hundred of them.
     */
    if (response.status === 403 && body.includes('quotaExceeded')) {
      throw new Error('YouTube daily quota exhausted; it resets at midnight Pacific');
    }

    /*
     * The one that wastes an afternoon. An "AQ." key is bound to a service
     * account and its API restriction is fixed to Gemini and Vertex, so
     * YouTube can never accept it however many APIs the project has enabled.
     * The console offers no way to widen it; a different key is the only fix.
     *
     * The diagnosis keys off the PREFIX rather than the response, because
     * Google gives two different answers for the same cause: 401 "API keys are
     * not supported by this API" to one caller and 400 "API key not valid" to
     * another, seemingly on headers alone. Both send people hunting for an
     * OAuth flow that is not the problem. The prefix does not vary.
     */
    if (isGeminiOnlyKey(apiKey)) {
      throw new Error(GEMINI_ONLY_HINT);
    }

    if (response.status === 403) throw new Error('YouTube rejected the API key');
    if (response.status === 400 || response.status === 401) {
      throw new Error('YouTube rejected the API key as invalid for this API');
    }
    return null;
  }
  return (await response.json()) as T;
}

interface ChannelItem {
  id: string;
  snippet: { title: string; customUrl?: string; publishedAt: string };
  statistics: {
    /** Rounded down to three significant figures by YouTube, always. */
    subscriberCount?: string;
    viewCount?: string;
    videoCount?: string;
    /** A channel may hide this, in which case the count is meaningless. */
    hiddenSubscriberCount?: boolean;
  };
  contentDetails?: { relatedPlaylists?: { uploads?: string } };
}

interface VideoItem {
  id: string;
  snippet: { title: string; publishedAt: string; thumbnails?: Record<string, { url: string }> };
  statistics?: { viewCount?: string; likeCount?: string; commentCount?: string };
  contentDetails?: { duration?: string };
}

const num = (value: string | undefined): number => {
  const parsed = Number(value ?? '0');
  return Number.isFinite(parsed) ? parsed : 0;
};

/** ISO 8601 duration to seconds. Shorts are the ones at or under a minute. */
function seconds(iso: string | undefined): number {
  if (!iso) return 0;
  const m = /^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso);
  if (!m) return 0;
  return Number(m[1] ?? 0) * 3600 + Number(m[2] ?? 0) * 60 + Number(m[3] ?? 0);
}

export async function fetchYoutube(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<YoutubeData>> {
  const apiKey = key();
  const channel = (process.env.YOUTUBE_CHANNEL_ID ?? '').trim();

  /*
   * Both caught before the request, so the panel names the actual problem
   * rather than reporting a rejection the user would reasonably read as
   * "wrong channel" and then spend an afternoon on.
   */
  if (apiKey && isTruncatedKey(apiKey)) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'YouTube',
      setupHint: SHADOWED_HINT,
    };
  }

  if (apiKey && isGeminiOnlyKey(apiKey)) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'YouTube',
      setupHint: GEMINI_ONLY_HINT,
    };
  }

  if (!apiKey || !channel) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'YouTube',
      setupHint:
        'Create a project at console.cloud.google.com, enable "YouTube Data API v3", make an API key and set YOUTUBE_API_KEY. Then set YOUTUBE_CHANNEL_ID to your channel id (the UC... string in your channel URL) or your @handle.',
    };
  }

  // A handle has to be exchanged for an id; the statistics endpoint takes ids.
  const selector = channel.startsWith('@')
    ? `forHandle=${encodeURIComponent(channel)}`
    : `id=${encodeURIComponent(channel)}`;

  const channels = await api<{ items?: ChannelItem[] }>(
    `channels?part=snippet,statistics,contentDetails&${selector}`,
    apiKey,
    signal,
  );
  const item = channels?.items?.[0];
  if (!item) {
    throw new Error(`No channel found for ${channel}`);
  }

  const uploads = item.contentDetails?.relatedPlaylists?.uploads;
  let videos: YoutubeVideo[] = [];

  if (uploads) {
    const playlist = await api<{ items?: Array<{ contentDetails: { videoId: string } }> }>(
      `playlistItems?part=contentDetails&maxResults=10&playlistId=${uploads}`,
      apiKey,
      signal,
    );
    const ids = (playlist?.items ?? []).map((v) => v.contentDetails.videoId).filter(Boolean);
    if (ids.length > 0) {
      const detail = await api<{ items?: VideoItem[] }>(
        `videos?part=snippet,statistics,contentDetails&id=${ids.join(',')}`,
        apiKey,
        signal,
      );
      videos = (detail?.items ?? []).map((v) => {
        const length = seconds(v.contentDetails?.duration);
        return {
          id: v.id,
          title: v.snippet.title,
          publishedAt: v.snippet.publishedAt,
          views: num(v.statistics?.viewCount),
          likes: num(v.statistics?.likeCount),
          comments: num(v.statistics?.commentCount),
          seconds: length,
          isShort: length > 0 && length <= 60,
          thumbnail: v.snippet.thumbnails?.medium?.url ?? v.snippet.thumbnails?.default?.url ?? '',
        };
      });
    }
  }

  const subscribers = num(item.statistics.subscriberCount);
  const totalViews = num(item.statistics.viewCount);
  const videoCount = num(item.statistics.videoCount);

  /*
   * Views per video across the last ten uploads, not across the channel's
   * lifetime. A five-year-old channel's lifetime average says nothing about
   * whether the current work lands.
   */
  const recentViews = videos.reduce((sum, v) => sum + v.views, 0);
  const recentAverage = videos.length > 0 ? Math.round(recentViews / videos.length) : 0;

  return {
    status: 'live',
    data: {
      channelId: item.id,
      title: item.snippet.title,
      handle: item.snippet.customUrl ?? '',
      subscribers,
      totalViews,
      videoCount,
      recentAverage,
      /** Share of the last ten uploads that are Shorts. */
      shortsShare: videos.length > 0 ? videos.filter((v) => v.isShort).length / videos.length : 0,
      videos,
    },
    error: null,
    fetchedAt: Date.now(),
    source: 'YouTube Data API v3',
  };
}

/**
 * Survey the channels working a theme.
 *
 * The figure that matters is not subscriber count -- a large old channel can
 * be dying quietly -- it is views per subscriber over recent uploads. Above
 * roughly 0.2 a channel is reaching past its own audience, which is the only
 * thing that grows a new one. Sorting by that surfaces the channels worth
 * copying rather than the channels that are merely big.
 *
 * Costs about 100 quota units for the search plus a handful for the details,
 * so it is not something to run on every turn.
 */
export async function scanChannels(
  theme: string,
  signal: AbortSignal,
  limit = 6,
): Promise<ChannelBenchmark[]> {
  const apiKey = key();
  if (!apiKey) throw new Error('YOUTUBE_API_KEY is not set');
  const query = theme.trim();
  if (!query) throw new Error('a theme is required');

  const found = await api<{ items?: Array<{ id: { channelId?: string } }> }>(
    `search?part=snippet&type=channel&order=relevance&maxResults=${Math.min(
      12,
      limit * 2,
    )}&q=${encodeURIComponent(query)}`,
    apiKey,
    signal,
  );
  const ids = (found?.items ?? [])
    .map((i) => i.id.channelId)
    .filter((id): id is string => Boolean(id));
  if (ids.length === 0) return [];

  const channels = await api<{ items?: ChannelItem[] }>(
    `channels?part=snippet,statistics,contentDetails&id=${ids.join(',')}`,
    apiKey,
    signal,
  );

  const out: ChannelBenchmark[] = [];
  for (const item of channels?.items ?? []) {
    /*
     * A channel may hide its subscriber count, and then the field is either
     * absent or zero. Ranking by views per subscriber would quietly send it to
     * the bottom as though it performed badly, so it is dropped instead: an
     * unmeasurable channel is not a weak one, and pretending otherwise is how
     * a benchmark starts lying.
     */
    if (item.statistics.hiddenSubscriberCount) continue;

    const subscribers = num(item.statistics.subscriberCount);
    // Below a few thousand subscribers the ratios are noise, not signal --
    // and the count is rounded to three significant figures anyway.
    if (subscribers < 2000) continue;

    const uploads = item.contentDetails?.relatedPlaylists?.uploads;
    let videos: VideoItem[] = [];
    if (uploads) {
      const playlist = await api<{ items?: Array<{ contentDetails: { videoId: string } }> }>(
        `playlistItems?part=contentDetails&maxResults=8&playlistId=${uploads}`,
        apiKey,
        signal,
      );
      const videoIds = (playlist?.items ?? []).map((v) => v.contentDetails.videoId);
      if (videoIds.length > 0) {
        const detail = await api<{ items?: VideoItem[] }>(
          `videos?part=snippet,statistics,contentDetails&id=${videoIds.join(',')}`,
          apiKey,
          signal,
        );
        videos = detail?.items ?? [];
      }
    }
    if (videos.length === 0) continue;

    const views = videos.map((v) => num(v.statistics?.viewCount));
    const lengths = videos.map((v) => seconds(v.contentDetails?.duration)).sort((a, b) => a - b);
    const recentAverage = Math.round(views.reduce((a, b) => a + b, 0) / views.length);

    const ranked = [...videos].sort(
      (a, b) => num(b.statistics?.viewCount) - num(a.statistics?.viewCount),
    );

    out.push({
      channelId: item.id,
      title: item.snippet.title,
      handle: item.snippet.customUrl ?? '',
      subscribers,
      videoCount: num(item.statistics.videoCount),
      recentAverage,
      viewsPerSubscriber: subscribers > 0 ? recentAverage / subscribers : 0,
      shortsShare: videos.filter((v) => seconds(v.contentDetails?.duration) <= 60).length / videos.length,
      medianSeconds: lengths[Math.floor(lengths.length / 2)] ?? 0,
      topTitles: ranked.slice(0, 3).map((v) => v.snippet.title),
    });
  }

  return out
    .sort((a, b) => b.viewsPerSubscriber - a.viewsPerSubscriber)
    .slice(0, limit);
}
