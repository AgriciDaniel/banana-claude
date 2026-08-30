'use client';

import { useEffect } from 'react';
import { loadFeed, setCoords, useFeedStore } from './store';
import { SERVER_MODULES } from './useModuleFeed';
import { useSystemStore } from '@/stores/useSystemStore';
import { useMusicFeed } from './useMusicFeed';
import { useSystemFeed } from './useSystemFeed';
import { log } from '@/stores/useLogStore';
import { t } from '@/i18n';

/**
 * Keeps every module fed.
 *
 * Mounted once. Loading all seven server modules from one place rather than
 * from each card means ten cards showing live numbers cost seven requests, not
 * seventy, and the ring is populated before anyone expands anything.
 *
 * Requests are staggered: firing seven fetches in the same tick competes with
 * the scene's own first frames, and the boot sequence is the one moment where
 * frame time is most visible.
 */

const STAGGER_MS = 220;
/** Background refresh for the ring faces. Expanded modules poll faster. */
const RING_REFRESH_MS = 300_000;

export function FeedDriver() {
  const boot = useSystemStore((s) => s.boot);
  const setFeed = useFeedStore((s) => s.set);

  // Client-measured modules have no route; their hooks write into the same
  // cache so the card faces read them exactly like the fetched ones.
  const system = useSystemFeed(boot === 'ready');
  const music = useMusicFeed(boot === 'ready');

  useEffect(() => {
    setFeed('system', system);
  }, [system, setFeed]);

  useEffect(() => {
    setFeed('music', music);
  }, [music, setFeed]);

  // Location, once, and only if the user is willing. Everything falls back to
  // the server's configured coordinates when they are not.
  useEffect(() => {
    if (boot !== 'ready' || !navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords(position.coords.latitude, position.coords.longitude);
        void loadFeed('weather', true);
      },
      () => {
        /* denied or unavailable — the server default stands */
      },
      { timeout: 8000, maximumAge: 600_000 },
    );
  }, [boot]);

  useEffect(() => {
    if (boot !== 'ready') return;
    const ids = [...SERVER_MODULES];
    const timers: number[] = [];

    ids.forEach((id, i) => {
      timers.push(
        window.setTimeout(() => {
          void loadFeed(id).then((feed) => {
            if (feed.status === 'error' && feed.error) {
              log.warn(t('log.feedError', { module: id.toUpperCase(), error: feed.error.slice(0, 30).toUpperCase() }));
            }
          });
        }, i * STAGGER_MS),
      );
    });

    const refresh = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      ids.forEach((id, i) => {
        timers.push(window.setTimeout(() => void loadFeed(id, true), i * STAGGER_MS));
      });
    }, RING_REFRESH_MS);

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      window.clearInterval(refresh);
    };
  }, [boot]);

  return null;
}
