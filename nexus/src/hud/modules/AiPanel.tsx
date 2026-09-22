'use client';

import { motion } from 'framer-motion';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { getAssistant } from '@/ai/AssistantEngine';
import { Line, Provenance, Section } from './shared';
import { useT, type TranslationKey } from '@/i18n';
import type { ModuleFeed } from '@/modules/types';

/**
 * The assistant, as a module.
 *
 * Not a second assistant - the same engine the wake phrase drives, surfaced so
 * it can be used deliberately rather than only conversationally. The prompts
 * below are the four things the brief asked for: knowledge search, reasoning,
 * summarising and code help, each one a real question sent through the real
 * pipeline.
 */

const ACTIONS: Array<{ key: TranslationKey; prompt: TranslationKey }> = [
  { key: 'ai.action.brief', prompt: 'ai.prompt.brief' },
  { key: 'ai.action.explain', prompt: 'ai.prompt.explain' },
  { key: 'ai.action.market', prompt: 'ai.prompt.market' },
  { key: 'ai.action.code', prompt: 'ai.prompt.code' },
];

export function AiPanel({ feed }: { feed: ModuleFeed<unknown> }) {
  const t = useT();
  const status = useAssistantStore((s) => s.status);
  const available = useAssistantStore((s) => s.available);
  const voice = useAssistantStore((s) => s.voice);
  const history = useAssistantStore((s) => s.history);

  if (!available) {
    return (
      <div className="py-3">
        <p className="font-mono text-[10px] tracking-[0.2em] text-ember">{t('ai.offlineTitle')}</p>
        <p className="mt-2 font-mono text-[10px] leading-[17px] tracking-[0.06em] text-ghost">
          {t('ai.offlineBody')}
        </p>
      </div>
    );
  }

  const exchanges = history.filter((m) => m.text).slice(-6);

  return (
    <div>
      <Section title={t('ai.state')}>
        <Line label={t('gesture.state')} value={t(`ai.status.${status}` as TranslationKey)} />
        <Line label={t('ai.voice')} value={t(`ai.voice.${voice}` as TranslationKey)} tone="muted" />
      </Section>

      <Section title={t('ai.ask')}>
        <div className="grid grid-cols-2 gap-1.5">
          {ACTIONS.map((action) => (
            <button
              key={action.key}
              type="button"
              onClick={() => void getAssistant().ask(t(action.prompt))}
              className="hud-panel px-2 py-2 text-left font-mono text-[9.5px] leading-[14px] tracking-[0.08em] text-ghost transition-colors hover:border-signal/45 hover:text-signal"
            >
              {t(action.key)}
            </button>
          ))}
        </div>
      </Section>

      {exchanges.length > 0 && (
        <Section title={t('ai.transcript')}>
          {exchanges.map((message) => (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              className="border-b border-signal/8 py-2 last:border-0"
            >
              <p
                className={`font-mono text-[8.5px] tracking-[0.18em] ${
                  message.role === 'user' ? 'text-ghost' : 'text-signal'
                }`}
              >
                {message.role === 'user' ? t('ai.you') : 'NEXUS'}
              </p>
              <p className="mt-1 font-sans text-[11.5px] leading-[17px] text-lumen/85">
                {message.text}
              </p>
              {message.sources && message.sources.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {message.sources.map((source) => (
                    <a
                      key={source.uri}
                      href={source.uri}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="font-mono text-[8.5px] tracking-[0.1em] text-ghost underline decoration-signal/30 transition-colors hover:text-signal"
                    >
                      {source.title || 'source'}
                    </a>
                  ))}
                </div>
              )}
            </motion.div>
          ))}
        </Section>
      )}

      <p className="mt-1 font-mono text-[9px] leading-[15px] tracking-[0.1em] text-signal/70">
        {t('ai.note')}
      </p>
      <Provenance feed={feed} />
    </div>
  );
}
