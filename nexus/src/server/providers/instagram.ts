import type { InstagramData, InstagramPost, ModuleFeed } from '@/modules/types';

/**
 * Instagram.
 *
 * There are two ways in, and which one applies depends on something outside
 * this code: whether the account is linked to a Facebook PAGE or only to a
 * personal profile.
 *
 *   Route A - "Instagram API with Instagram Login" (graph.instagram.com).
 *     No Facebook Page required. The token identifies the account, so `/me`
 *     resolves it and no user id is needed. This is the route to take unless
 *     you already run a Page.
 *
 *   Route B - Graph API via Facebook Login (graph.facebook.com).
 *     Requires the Instagram account to be connected to a Page. Linking
 *     Instagram to a personal profile through Accounts Center does NOT count.
 *
 * The route is chosen by which variables are present rather than by a flag,
 * because the presence of a user id is exactly what distinguishes them.
 *
 * Neither route works at all on a personal account: no API returns insights
 * for one, whatever the token. That check belongs in the app, not here.
 */

const GRAPH_FACEBOOK = 'https://graph.facebook.com/v21.0';
const GRAPH_INSTAGRAM = 'https://graph.instagram.com';

/**
 * The insights edge returns two different shapes. Time-series metrics carry a
 * `values` array; everything else carries a single `total_value` and requires
 * `metric_type=total_value` on the request. Handling only the first shape was
 * why several metrics came back as zero.
 */
interface InsightValue {
  name: string;
  values?: Array<{ value: number; end_time?: string }>;
  total_value?: { value: number };
}

/** Latest number from either shape. */
function readMetric(data: InsightValue[] | undefined, name: string): number {
  const entry = data?.find((d) => d.name === name);
  if (!entry) return 0;
  if (typeof entry.total_value?.value === 'number') return entry.total_value.value;
  return entry.values?.at(-1)?.value ?? 0;
}

async function graph<T>(
  base: string,
  path: string,
  token: string,
  signal: AbortSignal,
): Promise<T | null> {
  try {
    const separator = path.includes('?') ? '&' : '?';
    const response = await fetch(`${base}/${path}${separator}access_token=${token}`, {
      signal,
      next: { revalidate: 900 },
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

/** Read the token under either name; the vault convention is IG_GRAPH_TOKEN. */
function readToken(): string | undefined {
  return process.env.INSTAGRAM_TOKEN ?? process.env.IG_GRAPH_TOKEN;
}

export async function fetchInstagram(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<InstagramData>> {
  const token = readToken();
  const userId = process.env.INSTAGRAM_USER_ID;

  if (!token) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'Instagram',
      setupHint:
        'The account must be Professional or Creator first - a personal account returns no statistics from any API. Then create an app at developers.facebook.com, add the Instagram product with "Instagram Login", and set IG_GRAPH_TOKEN to the long-lived token. Run "npm run instagram:check" to verify it.',
    };
  }

  // No user id means Route A, where the token itself identifies the account.
  const usingInstagramLogin = !userId;
  const base = usingInstagramLogin ? GRAPH_INSTAGRAM : GRAPH_FACEBOOK;
  const me = usingInstagramLogin ? 'me' : userId;

  const profile = await graph<{
    username: string;
    followers_count?: number;
    follows_count?: number;
    media_count?: number;
    account_type?: string;
  }>(
    base,
    `${me}?fields=username,account_type,followers_count,follows_count,media_count`,
    token,
    signal,
  );

  if (!profile) {
    throw new Error(
      usingInstagramLogin
        ? 'Instagram rejected the token, or the account is still personal'
        : 'Graph API rejected the token, or the account is not linked to a Facebook Page',
    );
  }

  /*
   * A personal account authenticates fine and then returns no counts at all,
   * which is the single most confusing failure here. Say so explicitly rather
   * than rendering a profile full of zeroes.
   */
  if (profile.account_type && profile.account_type === 'PERSONAL') {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'Instagram',
      setupHint: `@${profile.username} is a personal account. Switch it to Professional or Creator in Settings, account type and tools - no API returns statistics for a personal account.`,
    };
  }

  const followers = profile.followers_count ?? 0;

  /*
   * Two calls, because the metrics need different request shapes. `reach`
   * supports a time series; `views` and `accounts_engaged` are total_value
   * only. Asking for all three in one call fails the whole request.
   *
   * `impressions` and `profile_views` are gone: the first was deprecated on
   * 21 April 2025 in favour of `views`, and the second no longer exists on
   * this edge at all.
   */
  const [reachInsight, totals, followerSeries, media] = await Promise.all([
    graph<{ data: InsightValue[] }>(base, `${me}/insights?metric=reach&period=day`, token, signal),
    graph<{ data: InsightValue[] }>(
      base,
      `${me}/insights?metric=views,accounts_engaged&period=day&metric_type=total_value`,
      token,
      signal,
    ),
    graph<{ data: InsightValue[] }>(
      base,
      `${me}/insights?metric=follower_count&period=day`,
      token,
      signal,
    ),
    graph<{
      data: Array<{
        id: string;
        caption?: string;
        media_type: string;
        media_url?: string;
        thumbnail_url?: string;
        permalink: string;
        like_count?: number;
        comments_count?: number;
        timestamp: string;
      }>;
    }>(
      base,
      `${me}/media?fields=id,caption,media_type,media_url,thumbnail_url,permalink,like_count,comments_count,timestamp&limit=24`,
      token,
      signal,
    ),
  ]);

  const reach = readMetric(reachInsight?.data, 'reach');

  const posts: InstagramPost[] = (media?.data ?? []).map((item) => ({
    id: item.id,
    caption: (item.caption ?? '').slice(0, 140),
    mediaType: item.media_type,
    url: item.thumbnail_url ?? item.media_url ?? '',
    permalink: item.permalink,
    likes: item.like_count ?? 0,
    comments: item.comments_count ?? 0,
    reach: 0,
    timestamp: Date.parse(item.timestamp),
  }));

  const engagement = posts.slice(0, 12);
  const engagementRate =
    followers > 0 && engagement.length > 0
      ? (engagement.reduce((sum, p) => sum + p.likes + p.comments, 0) /
          engagement.length /
          followers) *
        100
      : 0;

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: 'Instagram Graph API',
    data: {
      username: profile.username,
      followers,
      follows: profile.follows_count ?? 0,
      posts: profile.media_count ?? posts.length,
      reach,
      views: readMetric(totals?.data, 'views'),
      accountsEngaged: readMetric(totals?.data, 'accounts_engaged'),
      growth: (followerSeries?.data[0]?.values ?? []).map((v) => ({
        day: v.end_time?.slice(0, 10) ?? '',
        value: v.value,
      })),
      engagementRate,
      reels: posts.filter((p) => p.mediaType === 'VIDEO' || p.mediaType === 'REELS').length,
      top: [...posts].sort((a, b) => b.likes + b.comments - (a.likes + a.comments)).slice(0, 6),
    },
  };
}
