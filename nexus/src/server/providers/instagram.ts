import type { InstagramData, InstagramPost, ModuleFeed } from '@/modules/types';

/**
 * Instagram, from the Graph API.
 *
 * This one genuinely cannot be made to work without credentials. Insights are
 * only exposed for Business or Creator accounts, behind a long-lived access
 * token obtained through a Facebook app review flow - there is no public
 * endpoint, no key-less tier and no way to infer any of it.
 *
 * So the module is built in full against the real API shape, and without a
 * token it reports `unconfigured` and says exactly what is missing. It does not
 * invent a follower count.
 */

const GRAPH = 'https://graph.facebook.com/v21.0';

interface InsightValue {
  name: string;
  values: Array<{ value: number; end_time?: string }>;
}

async function graph<T>(path: string, token: string, signal: AbortSignal): Promise<T | null> {
  try {
    const separator = path.includes('?') ? '&' : '?';
    const response = await fetch(`${GRAPH}/${path}${separator}access_token=${token}`, {
      signal,
      next: { revalidate: 900 },
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchInstagram(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<InstagramData>> {
  const token = process.env.INSTAGRAM_TOKEN;
  const userId = process.env.INSTAGRAM_USER_ID;

  if (!token || !userId) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'Instagram Graph API',
      setupHint:
        'Needs a Business or Creator account. Set INSTAGRAM_USER_ID and INSTAGRAM_TOKEN (a long-lived Graph API token with instagram_basic and instagram_manage_insights).',
    };
  }

  const profile = await graph<{
    username: string;
    followers_count: number;
    follows_count: number;
    media_count: number;
  }>(`${userId}?fields=username,followers_count,follows_count,media_count`, token, signal);

  if (!profile) {
    throw new Error('Graph API rejected the token or the account is not a Business account');
  }

  const [accountInsights, followerSeries, media] = await Promise.all([
    graph<{ data: InsightValue[] }>(
      `${userId}/insights?metric=reach,impressions,profile_views&period=day`,
      token,
      signal,
    ),
    graph<{ data: InsightValue[] }>(
      `${userId}/insights?metric=follower_count&period=day`,
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
      `${userId}/media?fields=id,caption,media_type,media_url,thumbnail_url,permalink,like_count,comments_count,timestamp&limit=24`,
      token,
      signal,
    ),
  ]);

  const metric = (name: string): number =>
    accountInsights?.data.find((d) => d.name === name)?.values.at(-1)?.value ?? 0;

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
    profile.followers_count > 0 && engagement.length > 0
      ? (engagement.reduce((sum, p) => sum + p.likes + p.comments, 0) /
          engagement.length /
          profile.followers_count) *
        100
      : 0;

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: 'Instagram Graph API',
    data: {
      username: profile.username,
      followers: profile.followers_count,
      follows: profile.follows_count,
      posts: profile.media_count,
      reach: metric('reach'),
      impressions: metric('impressions'),
      profileViews: metric('profile_views'),
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
