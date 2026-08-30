'use client';

import { motion } from 'framer-motion';
import { LOCALES, useLocaleStore } from '@/i18n';
import { log } from '@/stores/useLogStore';
import { getAudio } from '@/audio/AudioEngine';
import { t } from '@/i18n';

/**
 * Language switch.
 *
 * A segmented control rather than a dropdown: there are two languages, both
 * fit on screen, and a native <select> would be the one piece of stock browser
 * chrome in the entire interface. Labels stay in their own language and are
 * marked `translate="no"` so they survive machine translation.
 */
export function LocaleSwitch({ compact = false }: { compact?: boolean }) {
  const locale = useLocaleStore((s) => s.locale);
  const setLocale = useLocaleStore((s) => s.setLocale);

  const select = (next: (typeof LOCALES)[number]) => {
    if (next.code === locale) return;
    setLocale(next.code);
    getAudio().tick();
    // Logged after the switch, so the confirmation itself is already localised.
    log.sys(t('log.language', { language: next.label.toUpperCase() }));
  };

  return (
    <div
      className="flex items-center gap-1"
      role="radiogroup"
      aria-label={t('boot.language')}
      translate="no"
    >
      {!compact && <span className="hud-label mr-1">{t('boot.language')}</span>}
      {LOCALES.map((entry) => {
        const active = entry.code === locale;
        return (
          <button
            key={entry.code}
            type="button"
            role="radio"
            aria-checked={active}
            lang={entry.tag}
            onClick={() => select(entry)}
            className={`relative px-2 py-1 font-mono text-[10px] tracking-[0.2em] transition-colors duration-200 ${
              active ? 'text-lumen' : 'text-ghost hover:text-signal'
            }`}
          >
            {compact ? entry.short : entry.label}
            {active && (
              <motion.span
                layoutId={compact ? 'locale-underline-compact' : 'locale-underline'}
                className="absolute inset-x-1 -bottom-0.5 h-px bg-signal"
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
