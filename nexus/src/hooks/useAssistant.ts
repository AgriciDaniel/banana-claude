'use client';

import { useEffect } from 'react';
import { disposeAssistant, getAssistant } from '@/ai/AssistantEngine';
import { useSystemStore } from '@/stores/useSystemStore';
import { useLocaleStore } from '@/i18n';
import { installDevBridge } from '@/ai/devBridge';

/**
 * Mounts the assistant.
 *
 * Deliberately gated on `boot === 'ready'` and on audio being unlocked: the
 * microphone prompt and the AudioContext both require the user gesture the
 * boot screen already collected, and asking for a microphone before someone
 * has even seen the interface is how a product gets denied permission forever.
 */
export function useAssistant() {
  const boot = useSystemStore((s) => s.boot);
  const audioUnlocked = useSystemStore((s) => s.audioUnlocked);
  const locale = useLocaleStore((s) => s.locale);

  useEffect(() => {
    if (boot !== 'ready') return;
    const assistant = getAssistant();
    void assistant.start();
    return () => disposeAssistant();
  }, [boot, audioUnlocked]);

  // window.__nexus — development only, removed from production builds.
  useEffect(() => installDevBridge(), []);

  // Recognition language follows the interface, so switching to French also
  // switches what the microphone is listening for.
  useEffect(() => {
    if (boot !== 'ready') return;
    getAssistant().syncLocale();
  }, [locale, boot]);
}
