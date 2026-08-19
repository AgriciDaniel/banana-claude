'use client';

import { useEffect, useState } from 'react';
import type { ModuleFeed, SystemData } from './types';
import { perf } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';

/**
 * System diagnostics.
 *
 * Measured in the browser, not fetched: every number here is something only
 * this tab can see. Battery, network and storage are all behind permissions or
 * vendor prefixes that vary by browser, so each is probed independently and
 * reported as null rather than guessed at when unavailable.
 */

interface BatteryLike extends EventTarget {
  level: number;
  charging: boolean;
}

interface ConnectionLike {
  effectiveType?: string;
  type?: string;
  downlink?: number;
  rtt?: number;
}

const started = Date.now();

export function useSystemFeed(active: boolean): ModuleFeed<SystemData> {
  const capabilities = useSystemStore((s) => s.capabilities);
  const [battery, setBattery] = useState<SystemData['battery']>(null);
  const [storage, setStorage] = useState<SystemData['storage']>(null);
  const [tick, setTick] = useState(0);

  // Battery emits change events; subscribing beats polling it.
  useEffect(() => {
    let disposed = false;
    const nav = navigator as Navigator & { getBattery?: () => Promise<BatteryLike> };
    if (!nav.getBattery) return;

    let handle: BatteryLike | null = null;
    const read = () => {
      if (handle && !disposed) setBattery({ level: handle.level, charging: handle.charging });
    };

    void nav.getBattery().then((b) => {
      if (disposed) return;
      handle = b;
      read();
      b.addEventListener('levelchange', read);
      b.addEventListener('chargingchange', read);
    });

    return () => {
      disposed = true;
      handle?.removeEventListener('levelchange', read);
      handle?.removeEventListener('chargingchange', read);
    };
  }, []);

  useEffect(() => {
    if (!navigator.storage?.estimate) return;
    void navigator.storage.estimate().then((estimate) => {
      if (estimate.usage != null && estimate.quota != null) {
        setStorage({
          usedMb: Math.round(estimate.usage / 1e6),
          quotaMb: Math.round(estimate.quota / 1e6),
        });
      }
    });
  }, []);

  // Frame stats change constantly; sample them rather than subscribing, and
  // only while the module is actually open.
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setTick((t) => t + 1), 500);
    return () => window.clearInterval(timer);
  }, [active]);

  const memory = (performance as Performance & {
    memory?: { usedJSHeapSize: number; jsHeapSizeLimit: number };
  }).memory;

  const connection = (navigator as Navigator & { connection?: ConnectionLike }).connection;

  void tick;

  return {
    status: 'live',
    error: null,
    fetchedAt: Date.now(),
    source: 'Browser diagnostics',
    data: {
      cores: navigator.hardwareConcurrency || 0,
      memoryGb: (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 0,
      heapUsedMb: memory ? Math.round(memory.usedJSHeapSize / 1e6) : null,
      heapLimitMb: memory ? Math.round(memory.jsHeapSizeLimit / 1e6) : null,
      battery,
      network: connection
        ? {
            type: connection.effectiveType ?? connection.type ?? 'unknown',
            downlink: connection.downlink ?? 0,
            rtt: connection.rtt ?? 0,
          }
        : null,
      storage,
      gpu: capabilities?.gpu ?? 'unknown',
      renderer: capabilities?.webgl === 2 ? 'WebGL2' : 'WebGL1',
      fps: Math.round(perf.fps),
      frameMs: Math.round(perf.frameMs * 10) / 10,
      drawCalls: perf.drawCalls,
      triangles: perf.triangles,
      platform: navigator.platform || navigator.userAgent.slice(0, 40),
      uptimeSec: Math.round((Date.now() - started) / 1000),
    },
  };
}
