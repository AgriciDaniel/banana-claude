'use client';

import { create } from 'zustand';
import { emptyFeed, type ModuleFeed } from './types';

/**
 * Feed cache.
 *
 * One entry per module, shared by the 3D surface, the detail rail and the card
 * texture, so all three always show the same numbers. Fetches are deduplicated
 * by an in-flight map: expanding a module mounts several consumers at once, and
 * each of them asking independently would triple every API call.
 */

interface FeedState {
  feeds: Record<string, ModuleFeed<unknown>>;
  set: (id: string, feed: ModuleFeed<unknown>) => void;
  patch: (id: string, partial: Partial<ModuleFeed<unknown>>) => void;
  get: (id: string) => ModuleFeed<unknown>;
}

export const useFeedStore = create<FeedState>((set, get) => ({
  feeds: {},
  set: (id, feed) => set((s) => ({ feeds: { ...s.feeds, [id]: feed } })),
  patch: (id, partial) =>
    set((s) => ({
      feeds: { ...s.feeds, [id]: { ...(s.feeds[id] ?? emptyFeed()), ...partial } },
    })),
  get: (id) => get().feeds[id] ?? emptyFeed(),
}));

const inflight = new Map<string, Promise<ModuleFeed<unknown>>>();

/** Where the browser thinks it is. Set once, if the user allows it. */
let coords: { lat: number; lon: number } | null = null;

export function setCoords(lat: number, lon: number): void {
  coords = { lat, lon };
}

export async function loadFeed(id: string, force = false): Promise<ModuleFeed<unknown>> {
  const existing = useFeedStore.getState().get(id);
  if (!force && existing.status === 'live' && Date.now() - existing.fetchedAt < 60_000) {
    return existing;
  }

  const pending = inflight.get(id);
  if (pending && !force) return pending;

  const url = new URL(`/api/module/${id}`, window.location.origin);
  if (coords) {
    url.searchParams.set('lat', String(coords.lat));
    url.searchParams.set('lon', String(coords.lon));
  }

  useFeedStore.getState().patch(id, {
    status: existing.data ? 'stale' : 'loading',
    error: null,
  });

  const request = (async (): Promise<ModuleFeed<unknown>> => {
    try {
      const response = await fetch(url, { cache: 'no-store' });
      const feed = (await response.json()) as ModuleFeed<unknown>;
      // Keep the last good payload visible behind an error, so a transient
      // network blip does not empty a module the user is looking at.
      if (feed.status === 'error' && existing.data) {
        const merged = { ...feed, data: existing.data, status: 'stale' as const };
        useFeedStore.getState().set(id, merged);
        return merged;
      }
      useFeedStore.getState().set(id, feed);
      return feed;
    } catch (error) {
      const failure: ModuleFeed<unknown> = {
        status: existing.data ? 'stale' : 'error',
        data: existing.data,
        error: error instanceof Error ? error.message : String(error),
        fetchedAt: existing.fetchedAt,
        source: existing.source || id,
      };
      useFeedStore.getState().set(id, failure);
      return failure;
    } finally {
      inflight.delete(id);
    }
  })();

  inflight.set(id, request);
  return request;
}
