'use client';

import { useCallback, useEffect, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import { detectCapabilities } from '@/core/capabilities';
import { useSystemStore } from '@/stores/useSystemStore';
import { useHandTracking } from '@/hooks/useHandTracking';
import { usePointerFallback } from '@/hooks/usePointerFallback';
import { useKeyboardControls } from '@/hooks/useKeyboardControls';
import { useTelemetry } from '@/hooks/useTelemetry';
import { useAudioBindings } from '@/hooks/useAudioBindings';
import { useAssistant } from '@/hooks/useAssistant';
import { useAssistantShortcuts } from '@/hooks/useAssistantShortcuts';
import { getAudio } from '@/audio/AudioEngine';
import { log } from '@/stores/useLogStore';
import { t, useLocaleStore } from '@/i18n';
import { Stage } from '@/rendering/Stage';
import { HUD } from '@/hud/HUD';
import { BootSequence } from '@/hud/BootSequence';
import { Fallback } from '@/hud/Fallback';
import { FeedDriver } from '@/modules/FeedDriver';

/**
 * StrictMode intentionally double-invokes effects in development. Capability
 * detection is idempotent, but the log it writes is user-visible, so the boot
 * banner is latched to fire exactly once per document.
 */
let bootLogged = false;

/**
 * Application root.
 *
 * Owns exactly three things: capability detection, the boot gate, and wiring
 * the input hooks. Everything else is composed underneath and talks through
 * the stores. This file should stay boring — the moment feature logic starts
 * appearing here, the layering has gone wrong.
 */
export function NexusApp() {
  const boot = useSystemStore((s) => s.boot);
  const capabilities = useSystemStore((s) => s.capabilities);
  const setCapabilities = useSystemStore((s) => s.setCapabilities);
  const setBoot = useSystemStore((s) => s.setBoot);
  const setInput = useSystemStore((s) => s.setInput);
  const input = useSystemStore((s) => s.input);
  const setAudioUnlocked = useSystemStore((s) => s.setAudioUnlocked);

  const [handsRequested, setHandsRequested] = useState(false);
  const resolveLocale = useLocaleStore((s) => s.resolve);

  // Locale detection runs after mount so the server render and the first
  // client paint agree; only then does any translated string appear.
  useEffect(() => {
    resolveLocale();
  }, [resolveLocale]);

  useEffect(() => {
    const caps = detectCapabilities();
    setCapabilities(caps);
    if (!bootLogged) {
      bootLogged = true;
      log.sys(t('log.boot', { gpu: caps.gpu, cores: caps.cores }));
      log.sys(t('log.quality', { tier: t(`tier.${caps.suggestedTier}`) }));
    }
  }, [setCapabilities]);

  // Reflect the active input onto the document so CSS can respond (cursor).
  useEffect(() => {
    document.body.dataset.input = input;
  }, [input]);

  usePointerFallback();
  useKeyboardControls();
  useTelemetry();
  useAudioBindings();
  useHandTracking(handsRequested);
  useAssistant();
  useAssistantShortcuts();

  const enter = useCallback(
    async (useHands: boolean) => {
      // A single user gesture buys both the AudioContext and the camera prompt.
      const unlocked = await getAudio().unlock();
      setAudioUnlocked(unlocked);
      if (unlocked) getAudio().boot();

      setBoot('ready');
      if (useHands) {
        setHandsRequested(true);
      } else {
        setInput('pointer');
        log.sys(t('log.pointerMode'));
      }
    },
    [setAudioUnlocked, setBoot, setInput],
  );

  if (capabilities && !capabilities.webgl) {
    return <Fallback />;
  }

  return (
    <>
      {boot === 'ready' && (
        <>
          {/* Keeps every module's data current. Renders nothing. */}
          <FeedDriver />
          <Stage />
          <HUD />
        </>
      )}

      <AnimatePresence>
        {boot !== 'ready' && <BootSequence key="boot" onEnter={enter} />}
      </AnimatePresence>
    </>
  );
}
