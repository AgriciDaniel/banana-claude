'use client';

import { motion } from 'framer-motion';
import { MODULES } from '@/config/modules';
import { useLocaleStore, useT } from '@/i18n';
import { localizeModule } from '@/i18n/modules';
import { LocaleSwitch } from './LocaleSwitch';

/**
 * No-WebGL fallback.
 *
 * Not an error page. The modules, the palette and the typography are the same;
 * only the dimension is missing. A spatial OS that shows a broken-image icon
 * on a locked-down machine has failed at something more basic than rendering.
 */
export function Fallback() {
  const t = useT();
  const locale = useLocaleStore((s) => s.locale);
  return (
    <main className="relative min-h-screen overflow-y-auto bg-void px-6 py-16 text-lumen">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(110% 70% at 50% 0%, color-mix(in oklab, #2b6cff 14%, transparent) 0%, transparent 62%)',
        }}
      />

      <div className="relative mx-auto max-w-[820px]">
        <h1 className="font-sans text-[64px] font-extralight leading-none tracking-[0.06em]">
          NEXUS
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-4">
          <p className="font-mono text-[10px] tracking-[0.4em] text-ghost">
            {t('boot.subtitle')}
          </p>
          <LocaleSwitch />
        </div>

        <div className="hud-panel hud-ticks relative mt-10 p-5">
          <p className="font-mono text-[11px] leading-[19px] tracking-[0.1em] text-ember">
            {t('fallback.unavailable')}
          </p>
          <p className="mt-2 font-mono text-[10px] leading-[18px] tracking-[0.08em] text-ghost">
            {t('fallback.noWebgl').toUpperCase()}
          </p>
          <p className="mt-4 font-mono text-[10px] leading-[18px] tracking-[0.08em] text-ghost">
            {t('fallback.body')}
          </p>
        </div>

        <div className="mt-10 grid gap-3 sm:grid-cols-2">
          {MODULES.map((mod, i) => {
            const text = localizeModule(mod, locale);
            return (
            <motion.article
              key={mod.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }}
              className="hud-panel hud-ticks relative p-4"
            >
              <div className="flex items-baseline justify-between">
                <span className="font-sans text-[28px] font-extralight leading-none text-lumen">
                  {mod.code}
                </span>
                <span
                  className={`font-mono text-[9px] tracking-[0.2em] ${
                    mod.status === 'attention' ? 'text-ember' : 'text-ghost'
                  }`}
                >
                  {t(`state.${mod.status}`)}
                </span>
              </div>
              <h2 className="mt-2 font-sans text-[15px] font-medium tracking-tight">{text.name}</h2>
              <p className="mt-1 font-mono text-[9px] leading-[15px] tracking-[0.1em] text-ghost">
                {text.descriptor.toUpperCase()}
              </p>
            </motion.article>
            );
          })}
        </div>
      </div>
    </main>
  );
}
