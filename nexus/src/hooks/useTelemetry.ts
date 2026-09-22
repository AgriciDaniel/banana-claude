'use client';

import { useEffect } from 'react';
import { gestureSnapshot, interaction, perf, telemetry } from '@/stores/runtime';
import { MODULES } from '@/config/modules';
import { useCarouselStore } from '@/stores/useCarouselStore';

/** Discrete events stay on the HUD this long before decaying to the posture. */
const EVENT_HOLD_MS = 1200;

/**
 * The 10 Hz bridge.
 *
 * The render loop runs at up to 120 Hz and the HUD needs none of that. This is
 * the only thing that copies runtime values into a reactive store, and it does
 * so on an interval — which is why a 120 fps scene renders zero React trees.
 */
export function useTelemetry() {
  useEffect(() => {
    const id = window.setInterval(() => {
      telemetry.fps = Math.round(perf.fps);
      telemetry.frameMs = Math.round(perf.frameMs * 10) / 10;
      telemetry.drawCalls = perf.drawCalls;
      telemetry.triangles = perf.triangles;
      telemetry.handCount = gestureSnapshot.hands.length;
      telemetry.latency = Math.round(gestureSnapshot.latency * 10) / 10;
      telemetry.frozen = interaction.frozen;

      /*
       * The sampler stores translation KEYS, never translated text. Switching
       * language must not require waiting for the next 100 ms tick to relabel
       * the HUD — the components translate at render time instead.
       */
      const event = gestureSnapshot.lastEvent;
      const fresh = event && performance.now() - event.at < EVENT_HOLD_MS;
      if (fresh && event) {
        telemetry.gestureKey = `g.${event.kind}`;
        telemetry.gestureConfidence = event.confidence;
      } else if (gestureSnapshot.primary) {
        telemetry.gestureKey = `posture.${gestureSnapshot.posture}`;
        telemetry.gestureConfidence = gestureSnapshot.confidence;
      } else {
        telemetry.gestureKey = 'gesture.none';
        telemetry.gestureConfidence = 0;
      }

      const index = useCarouselStore.getState().focusedIndex;
      telemetry.frontModuleId = MODULES[index]?.id ?? '';
    }, 100);

    return () => window.clearInterval(id);
  }, []);
}
