'use client';

import { useEffect } from 'react';
import { loadFeed, useFeedStore } from './store';
import { emptyFeed, type ModuleFeed } from './types';

/** Modules whose data is fetched rather than measured locally. */
export const SERVER_MODULES = new Set([
  'weather',
  'stocks',
  'news',
  'sports',
  'projects',
  'calendar',
  'instagram',
  'youtube',
]);

/** How often a live module refreshes itself while it is on screen. */
const REFRESH_MS: Record<string, number> = {
  weather: 300_000,
  stocks: 60_000,
  news: 600_000,
  sports: 120_000,
  calendar: 300_000,
  projects: 900_000,
  instagram: 900_000,
  // Channel statistics move slowly and the Data API bills by quota, so this
  // refreshes at the same unhurried cadence as Instagram rather than polling.
  youtube: 900_000,
};

/**
 * Subscribe to a module's feed, fetching on mount and refreshing on a cadence
 * that suits the data: a share price is stale in a minute, a project's star
 * count is not.
 *
 * `active` gates the polling. Modules keep their last payload when collapsed
 * but stop hitting the network, so ten modules do not mean ten timers.
 */
export function useModuleFeed<T>(id: string, active = true): ModuleFeed<T> {
  const feed = useFeedStore((s) => s.feeds[id]) as ModuleFeed<T> | undefined;

  useEffect(() => {
    if (!SERVER_MODULES.has(id)) return;
    void loadFeed(id);
    if (!active) return;

    const period = REFRESH_MS[id] ?? 300_000;
    const timer = window.setInterval(() => {
      // Refreshing a backgrounded tab burns quota for nobody's benefit.
      if (document.visibilityState === 'visible') void loadFeed(id, true);
    }, period);
    return () => window.clearInterval(timer);
  }, [id, active]);

  return feed ?? emptyFeed<T>();
}
