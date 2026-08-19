'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useSnapshot } from 'valtio';
import { gestureSnapshot, telemetry } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { Meter, Panel, Row } from './primitives';
import { useT, type TranslationKey } from '@/i18n';

/**
 * Bottom right: what the system thinks your hands are doing.
 *
 * The confidence readout is not decoration. Gesture systems fail invisibly —
 * showing the confidence behind a call is what lets a user learn *why* a
 * gesture did not land, instead of concluding the whole thing is unreliable.
 */
export function GestureCluster() {
  const telem = useSnapshot(telemetry);
  const t = useT();
  const tracking = useSystemStore((s) => s.tracking);
  const [freeze, setFreeze] = useState(0);
  const raf = useRef(0);

  // The freeze ring is the one HUD element that must be frame-accurate: it is
  // feedback on a gesture in progress, so it reads the runtime directly.
  useEffect(() => {
    const tick = () => {
      raf.current = requestAnimationFrame(tick);
      setFreeze((prev) => {
        const next = gestureSnapshot.freezeProgress;
        return Math.abs(next - prev) > 0.01 ? next : prev;
      });
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, []);

  const label = t(telem.gestureKey as TranslationKey);
  const confident = telem.gestureConfidence > 0.6;
  const live = tracking === 'active';

  return (
    <Panel className="w-[228px]" delay={0.26} from="right">
      <div className="flex items-center justify-between">
        <span className="hud-label">{t('gesture.title')}</span>
        <span className="hud-label">
          {t(telem.handCount === 1 ? 'gesture.hands_one' : 'gesture.hands', { n: telem.handCount })}
        </span>
      </div>

      <div className="relative mt-1.5 flex h-[38px] items-center">
        <AnimatePresence mode="wait">
          <motion.span
            key={label}
            initial={{ opacity: 0, y: 8, filter: 'blur(4px)' }}
            animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -8, filter: 'blur(4px)' }}
            transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}
            className={`font-sans text-[22px] font-light tracking-[0.12em] ${
              confident ? 'text-lumen text-shadow-glow' : 'text-ghost'
            }`}
          >
            {label}
          </motion.span>
        </AnimatePresence>

        {/* Freeze charge ring — fills while a palm is held still. */}
        {freeze > 0.02 && (
          <svg className="absolute right-0 h-8 w-8 -rotate-90" viewBox="0 0 36 36" aria-hidden>
            <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" strokeWidth="2" className="text-lumen/10" />
            <circle
              cx="18"
              cy="18"
              r="15"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeDasharray={`${freeze * 94.2} 94.2`}
              className={freeze >= 1 ? 'text-ember' : 'text-signal'}
            />
          </svg>
        )}
      </div>

      <div className="py-1">
        <Meter
          value={telem.gestureConfidence}
          segments={20}
          tone={telem.frozen ? 'ember' : confident ? 'lock' : 'signal'}
        />
      </div>

      <Row
        label={t('gesture.confidence')}
        value={`${Math.round(telem.gestureConfidence * 100)}%`}
        tone={confident ? 'good' : 'muted'}
      />
      <Row
        label={t('gesture.latency')}
        value={live ? `${telem.latency.toFixed(1)} MS` : t('gesture.none')}
        tone="muted"
      />
      <Row
        label={t('gesture.state')}
        value={telem.frozen ? t('gesture.frozen') : t('gesture.live')}
        tone={telem.frozen ? 'warn' : 'good'}
      />
    </Panel>
  );
}
