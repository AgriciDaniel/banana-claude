'use client';

import { useEffect, useRef, useState } from 'react';
import { HandTracker } from '@/gesture/HandTracker';
import { GestureEngine } from '@/gesture/GestureEngine';
import { registerFramePublisher, cameraMuted } from '@/gesture/devFeed';
import { captureFrame } from '@/gesture/recorder';

const DEV = process.env.NODE_ENV !== 'production';
import { gestureSnapshot, interaction } from '@/stores/runtime';
import { bus } from '@/stores/bus';
import { useSystemStore } from '@/stores/useSystemStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { log } from '@/stores/useLogStore';
import { t } from '@/i18n';
import { RollingMean } from '@/core/math';

/**
 * Hand tracking lifecycle.
 *
 * Runs its OWN requestAnimationFrame loop rather than riding the render loop.
 * That separation is deliberate: inference is bound to the camera's frame rate
 * (typically 30 Hz) while rendering wants 60–120, and coupling them would
 * either throttle the renderer or run the model on stale frames.
 *
 * Inference is skipped entirely when the video has not produced a new frame,
 * so on a 30 fps camera this costs half of what a naive per-rAF loop would.
 */
export function useHandTracking(enabled: boolean) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [ready, setReady] = useState(false);
  const setTracking = useSystemStore((s) => s.setTracking);
  const setInput = useSystemStore((s) => s.setInput);

  useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    let raf = 0;
    let lostSince = 0;
    const rate = new RollingMean(30);
    let lastFrameAt = 0;

    const tracker = new HandTracker({ numHands: 2 });
    const engine = new GestureEngine();

    /**
     * Turn one inference result into interface state. Split out from the loop
     * so a synthetic frame can be pushed through the identical path -- see
     * `devFeed` -- rather than a parallel one that could drift from it.
     */
    const publish = (result: ReturnType<typeof tracker.detect> & object, now: number) => {
      const t0 = performance.now();
      engine.setGrabbing(useCarouselStore.getState().draggingId !== null);
      const out = engine.update(result, now);
      // The label on this number is "latency", so it has to cover the whole
      // path from camera frame to interface state. Inference dominates it by
      // two orders of magnitude; reporting only the detector cost made the
      // pipeline look ten times faster than it is.
      const latency = tracker.inferenceMs + (performance.now() - t0);

      if (lastFrameAt > 0) rate.push(1000 / Math.max(now - lastFrameAt, 1));
      lastFrameAt = now;

      gestureSnapshot.hands = out.hands;
      gestureSnapshot.primary = out.primary;
      gestureSnapshot.posture = out.posture;
      gestureSnapshot.confidence = out.confidence;
      gestureSnapshot.latency = latency;
      gestureSnapshot.freezeProgress = out.freezeProgress;
      gestureSnapshot.rate = rate.mean;

      // The spread dial is continuous, so it rides the runtime bus.
      interaction.spread = out.spread;
      interaction.twoHanded = out.twoHanded;

      for (const event of out.events) {
        gestureSnapshot.lastEvent = event;
        bus.emit('gesture', event);
      }

      // Tracking status is derived, not asserted: "active" means a hand is
      // actually in frame right now, which is what the HUD should report.
      const state = useSystemStore.getState();
      if (out.hands.length > 0) {
        lostSince = 0;
        if (state.tracking !== 'active') setTracking('active');
        if (state.input !== 'hand') setInput('hand');
      } else {
        if (lostSince === 0) lostSince = now;
        else if (now - lostSince > 900 && state.tracking === 'active') setTracking('lost');
      }
    };

    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (disposed) return;

      // The rehearsal seam and the recorder are development instruments.
      // Behind a build-time constant they fold away entirely, so production
      // neither calls them nor carries them.
      if (DEV && cameraMuted()) return;

      const now = performance.now();
      const result = tracker.detect(now);
      // No new camera frame — nothing to infer, nothing to publish.
      if (!result) return;
      if (DEV) captureFrame(result, now);
      publish(result, now);
    };

    if (DEV) {
      registerFramePublisher((result, now) => {
        if (!disposed) publish(result, now);
      });
    }

    (async () => {
      setTracking('requesting');
      log.sys(t('log.cameraRequest'));
      try {
        await tracker.init();
      } catch {
        if (disposed) return;
        const denied = tracker.phase === 'denied';
        setTracking(denied ? 'denied' : 'error', tracker.error);
        log.warn(
          denied
            ? t('log.cameraDenied')
            : t('log.trackingFailed', { error: tracker.error ?? '?' }),
        );
        useSystemStore.getState().setInput('pointer');
        return;
      }
      if (disposed) return;

      videoRef.current = tracker.video;
      setReady(true);
      setTracking('active');
      setInput('hand');
      log.ok(t('log.trackingOnline', { delegate: tracker.gpuDelegate ? 'GPU' : 'CPU' }));
      raf = requestAnimationFrame(loop);
    })();

    return () => {
      disposed = true;
      if (DEV) registerFramePublisher(null);
      cancelAnimationFrame(raf);
      tracker.dispose();
      engine.reset();
      videoRef.current = null;
      setReady(false);
      gestureSnapshot.hands = [];
      gestureSnapshot.primary = null;
      interaction.frozen = false;
      useSystemStore.getState().setTracking('idle');
    };
  }, [enabled, setInput, setTracking]);

  return { video: videoRef, ready };
}
