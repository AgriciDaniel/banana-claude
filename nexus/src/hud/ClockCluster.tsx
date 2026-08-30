'use client';

import { useEffect, useState } from 'react';
import { Panel } from './primitives';
import { useLocaleTag } from '@/i18n';

/**
 * Top right: time.
 *
 * Rendered null on the server and on the first client paint — a clock is the
 * classic hydration mismatch, and the honest fix is to admit the server does
 * not know what time it is where you are.
 */
export function ClockCluster() {
  const [now, setNow] = useState<Date | null>(null);
  const tag = useLocaleTag();

  useEffect(() => {
    setNow(new Date());
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!now) return null;

  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const ss = String(now.getSeconds()).padStart(2, '0');

  // Formatted in the SELECTED locale, not the browser's — picking French
  // should change the date too, or the panel reads as half-translated.
  const date = now
    .toLocaleDateString(tag, { weekday: 'short', day: '2-digit', month: 'short' })
    .toUpperCase();

  const zone =
    Intl.DateTimeFormat().resolvedOptions().timeZone?.split('/').pop()?.replace(/_/g, ' ') ?? 'LOCAL';

  return (
    <Panel className="w-[196px] text-right" delay={0.18} from="right">
      <div className="flex items-baseline justify-end gap-1 font-mono tabular-nums">
        <span className="text-[30px] font-light leading-none tracking-tight text-lumen">
          {hh}:{mm}
        </span>
        <span className="text-[15px] leading-none text-signal">{ss}</span>
      </div>
      <div className="mt-2 flex items-center justify-end gap-2">
        <span className="hud-label">{date}</span>
        <span className="h-2.5 w-px bg-signal/25" />
        <span className="hud-label">{zone}</span>
      </div>
    </Panel>
  );
}
