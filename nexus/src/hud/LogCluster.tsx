'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useSnapshot } from 'valtio';
import { useLogStore, type LogLevel } from '@/stores/useLogStore';
import { telemetry } from '@/stores/runtime';
import { Panel } from './primitives';
import { useLocaleStore, useT } from '@/i18n';
import { moduleById } from '@/config/modules';
import { localizeModule } from '@/i18n/modules';

const TONE: Record<LogLevel, string> = {
  sys: 'text-ghost',
  gesture: 'text-signal',
  ok: 'text-lock',
  warn: 'text-ember',
};

const GLYPH: Record<LogLevel, string> = {
  sys: '·',
  gesture: '›',
  ok: '+',
  warn: '!',
};

/**
 * Bottom left: the system log.
 *
 * Capped at seven lines and de-duplicated at the store, because a log that
 * scrolls faster than you can read is decoration. Every line here corresponds
 * to something the user actually did.
 */
export function LogCluster() {
  const entries = useLogStore((s) => s.entries);
  const telem = useSnapshot(telemetry);
  const t = useT();
  const locale = useLocaleStore((s) => s.locale);
  const front = moduleById(telem.frontModuleId);

  return (
    <Panel className="w-[292px]" delay={0.34} from="left">
      <div className="flex items-center justify-between">
        <span className="hud-label">{t('log.title')}</span>
        <span className="hud-label">
          {front ? localizeModule(front, locale).name.toUpperCase() : t('gesture.none')}
        </span>
      </div>

      <div className="mt-2 flex min-h-[112px] flex-col justify-end gap-[3px]">
        <AnimatePresence initial={false}>
          {entries.map((entry) => (
            <motion.div
              key={entry.id}
              layout
              initial={{ opacity: 0, x: -10, filter: 'blur(3px)' }}
              animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
              className="flex items-baseline gap-2 font-mono text-[10px] leading-[15px]"
            >
              <span className="text-ghost/60 tabular-nums">{entry.t}</span>
              <span className={`${TONE[entry.level]} w-2 text-center`}>{GLYPH[entry.level]}</span>
              <span className={`${TONE[entry.level]} truncate`}>{entry.text}</span>
            </motion.div>
          ))}
        </AnimatePresence>

        {entries.length === 0 && (
          <span className="font-mono text-[10px] text-ghost/50">{t('log.awaiting')}</span>
        )}
      </div>
    </Panel>
  );
}
