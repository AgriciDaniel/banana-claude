'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useSystemStore } from '@/stores/useSystemStore';
import { StatusCluster } from './StatusCluster';
import { ClockCluster } from './ClockCluster';
import { GestureCluster } from './GestureCluster';
import { LogCluster } from './LogCluster';
import { ExpandedPanel } from './ExpandedPanel';
import { HandOverlay } from './HandOverlay';
import { GestureLegend } from './GestureLegend';
import { useEffect } from 'react';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { useT } from '@/i18n';
import { AssistantPanel } from './ai/AssistantPanel';
import { EnvironmentSwitcher } from './EnvironmentSwitcher';

/**
 * HUD layout.
 *
 * Four corners, nothing in the middle. The centre of the screen belongs to the
 * ring; every readout is pushed to the periphery where it can be glanced at
 * without being looked at. Press H to remove even that.
 */
export function HUD() {
  const visible = useSystemStore((s) => s.hud);
  const diagnostics = useSystemStore((s) => s.diagnostics);
  const tracking = useSystemStore((s) => s.tracking);
  const awake = useAssistantStore((s) => s.awake);
  const t = useT();

  // Drive the CSS glow from a data attribute rather than threading a prop
  // through every panel — one write, and every `.hud-panel` responds.
  useEffect(() => {
    document.body.dataset.awake = awake ? 'true' : 'false';
  }, [awake]);

  return (
    <>
      <HandOverlay visible={diagnostics} />

      {/* Awake rim. Sits under the HUD and above the canvas. */}
      <div className="awake-rim z-10" aria-hidden />

      <div className="scanlines pointer-events-none fixed inset-0 z-20 select-none">
        <AnimatePresence>
          {visible && (
            <motion.div key="hud" exit={{ opacity: 0 }} transition={{ duration: 0.4 }}>
              <div className="absolute left-6 top-6 pointer-events-auto">
                <StatusCluster />
              </div>

              <div className="absolute right-6 top-6 pointer-events-auto">
                <ClockCluster />
              </div>

              <div className="absolute bottom-6 left-6 pointer-events-auto">
                <LogCluster />
              </div>

              <div className="absolute bottom-6 right-6 pointer-events-auto">
                <GestureCluster />
              </div>

              <GestureLegend />
              <AssistantPanel />
              <EnvironmentSwitcher />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Permission fault is the one message allowed to break the corners rule. */}
        <AnimatePresence>
          {(tracking === 'denied' || tracking === 'error') && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="hud-panel absolute left-1/2 top-6 -translate-x-1/2 px-4 py-2"
            >
              <span className="font-mono text-[10px] tracking-[0.2em] text-ember">
                {tracking === 'denied' ? t('hud.cameraDenied') : t('hud.trackingFault')}
                {' — '}
                {t('hud.fallbackActive')}
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="pointer-events-none fixed inset-0 z-20">
        <ExpandedPanel />
      </div>
    </>
  );
}
