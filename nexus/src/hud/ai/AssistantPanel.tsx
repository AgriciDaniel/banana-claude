'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { getAssistant } from '@/ai/AssistantEngine';
import { useT, type TranslationKey } from '@/i18n';
import { VoiceMeter } from './VoiceMeter';
import type { AssistantStatus } from '@/ai/types';

/**
 * The assistant's console.
 *
 * Appears only when there is something to say: awake, faulted, or offline.
 * Standby shows nothing at all, because a permanently visible assistant panel
 * turns an ambient presence back into an app window.
 *
 * The typed input is not a lesser path. Speech recognition is missing entirely
 * in several browsers and unusable in a noisy room, and an assistant that can
 * only be reached by voice is an assistant most people cannot reach.
 */

const TONE: Record<AssistantStatus, string> = {
  offline: 'text-ghost',
  standby: 'text-ghost',
  listening: 'text-lock',
  thinking: 'text-signal',
  streaming: 'text-signal',
  speaking: 'text-lumen',
  interrupted: 'text-ember',
};

const DOT: Record<AssistantStatus, string> = {
  offline: 'bg-ghost',
  standby: 'bg-ghost',
  listening: 'bg-lock',
  thinking: 'bg-signal',
  streaming: 'bg-signal',
  speaking: 'bg-lumen',
  interrupted: 'bg-ember',
};

export function AssistantPanel() {
  const t = useT();
  const status = useAssistantStore((s) => s.status);
  const awake = useAssistantStore((s) => s.awake);
  const available = useAssistantStore((s) => s.available);
  const micSupported = useAssistantStore((s) => s.micSupported);
  const transcript = useAssistantStore((s) => s.transcript);
  const transcriptFinal = useAssistantStore((s) => s.transcriptFinal);
  const error = useAssistantStore((s) => s.error);

  const [draft, setDraft] = useState('');
  const input = useRef<HTMLInputElement>(null);

  const speaking = status === 'speaking' || status === 'streaming';
  const visible = awake || !available || Boolean(error);

  // Focus the field the moment the assistant wakes without a microphone —
  // otherwise waking does nothing visible for a keyboard-only user.
  useEffect(() => {
    if (awake && !micSupported) input.current?.focus();
  }, [awake, micSupported]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setDraft('');
    void getAssistant().ask(text);
  };

  const hint: TranslationKey =
    status === 'thinking' || status === 'streaming'
      ? 'ai.hint.thinking'
      : speaking
        ? 'ai.hint.interrupt'
        : awake
          ? 'ai.hint.speak'
          : 'ai.hint.wake';

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 18, filter: 'blur(8px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, y: 18, filter: 'blur(8px)' }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="hud-panel hud-ticks pointer-events-auto absolute bottom-[104px] left-1/2 w-[520px] max-w-[calc(100vw-56px)] -translate-x-1/2 px-4 py-3"
        >
          {/* --- status line -------------------------------------------- */}
          <div className="flex items-center gap-3">
            <span className="relative flex h-1.5 w-1.5 shrink-0">
              {awake && (
                <motion.span
                  className={`absolute inline-flex h-full w-full rounded-full ${DOT[status]}`}
                  animate={{ opacity: [0.9, 0.15, 0.9], scale: [1, 2.4, 1] }}
                  transition={{ duration: status === 'thinking' ? 1 : 2.2, repeat: Infinity }}
                />
              )}
              <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${DOT[status]}`} />
            </span>

            <span
              className={`font-mono text-[10px] tracking-[0.24em] ${TONE[status]}`}
              translate="no"
            >
              {t(`ai.status.${status}` as TranslationKey)}
            </span>

            <span className="ml-auto flex items-center gap-3">
              <VoiceMeter active={speaking} />
              {awake && (
                <button
                  type="button"
                  onClick={() => getAssistant().sleep('manual')}
                  className="font-mono text-[9px] tracking-[0.2em] text-ghost transition-colors hover:text-ember"
                >
                  {t('ai.sleep')}
                </button>
              )}
            </span>
          </div>

          {/* --- offline ------------------------------------------------- */}
          {!available && (
            <div className="mt-2.5">
              <p className="font-mono text-[10px] tracking-[0.18em] text-ember">
                {t('ai.offlineTitle')}
              </p>
              <p className="mt-1 font-mono text-[9.5px] leading-[15px] tracking-[0.12em] text-ghost">
                {t('ai.offlineBody')}
              </p>
            </div>
          )}

          {/* --- live transcript ----------------------------------------- */}
          {available && transcript && (
            <p
              className={`mt-2.5 font-sans text-[13px] leading-[19px] ${
                transcriptFinal ? 'text-lumen' : 'text-ghost italic'
              }`}
            >
              <span className="hud-label mr-2">{t('ai.you')}</span>
              {transcript}
            </p>
          )}

          {available && error && (
            <p className="mt-2 font-mono text-[9.5px] leading-[15px] tracking-[0.12em] text-ember">
              {error}
            </p>
          )}

          {/* --- input --------------------------------------------------- */}
          {available && (
            <form onSubmit={submit} className="mt-2.5 flex items-center gap-2">
              <input
                ref={input}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={t('ai.placeholder')}
                aria-label={t('ai.placeholder')}
                className="min-w-0 flex-1 border-b border-signal/20 bg-transparent pb-1 font-sans text-[13px] text-lumen outline-none transition-colors placeholder:text-ghost/60 focus:border-signal/55"
              />
              <span className="font-mono text-[9px] tracking-[0.2em] text-ghost">
                {t(hint)}
              </span>
            </form>
          )}

          {available && !micSupported && (
            <p className="mt-2 font-mono text-[9px] tracking-[0.14em] text-ghost/70">
              {t('ai.noMic')}
            </p>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
