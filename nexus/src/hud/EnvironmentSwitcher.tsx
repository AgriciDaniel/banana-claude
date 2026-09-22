'use client';

import { motion } from 'framer-motion';
import { ENVIRONMENT_ORDER, ENVIRONMENTS } from '@/config/environments';
import { useEnvironmentStore } from '@/stores/useEnvironmentStore';
import { getAudio } from '@/audio/AudioEngine';
import { useT, type TranslationKey } from '@/i18n';

/**
 * World selector.
 *
 * Six dots along the left edge, one per environment. Deliberately not a
 * dropdown and not labelled by default: the worlds are meant to be tried, and
 * a list of names invites reading instead of switching.
 *
 * The active dot is marked with a shared layout indicator so switching worlds
 * animates the marker rather than teleporting it.
 */
export function EnvironmentSwitcher() {
  const t = useT();
  const preferred = useEnvironmentStore((s) => s.preferred);
  const active = useEnvironmentStore((s) => s.active);
  const overriddenBy = useEnvironmentStore((s) => s.overriddenBy);
  const setPreferred = useEnvironmentStore((s) => s.setPreferred);

  return (
    <div
      className="pointer-events-auto absolute left-6 top-1/2 -translate-y-1/2"
      role="radiogroup"
      aria-label={t('env.title')}
    >
      <p className="hud-label mb-2.5 origin-left -rotate-90 whitespace-nowrap opacity-60">
        {t('env.title')}
      </p>

      <div className="flex flex-col gap-1">
        {ENVIRONMENT_ORDER.map((id) => {
          const chosen = id === preferred;
          const showing = id === active;
          return (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={chosen}
              title={ENVIRONMENTS[id].name}
              onClick={() => {
                if (id === preferred) return;
                setPreferred(id);
                getAudio().brush();
              }}
              className="group relative flex items-center gap-2 py-1.5 pr-2"
            >
              {/* The dot. Filled when chosen, ringed when a module borrowed it. */}
              <span
                className={`relative h-[7px] w-[7px] rotate-45 border transition-colors duration-300 ${
                  chosen
                    ? 'border-signal bg-signal'
                    : showing
                      ? 'border-signal/70 bg-transparent'
                      : 'border-ghost/45 bg-transparent group-hover:border-signal/70'
                }`}
              />

              {showing && (
                <motion.span
                  layoutId="env-marker"
                  className="absolute -left-[9px] h-[7px] w-[2px] bg-signal"
                  transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                />
              )}

              {/* Name appears on hover only, so the rail stays quiet. */}
              <span className="pointer-events-none whitespace-nowrap font-mono text-[9px] tracking-[0.16em] text-ghost opacity-0 transition-opacity duration-200 group-hover:opacity-100">
                {t(`env.${id}` as TranslationKey)}
              </span>
            </button>
          );
        })}
      </div>

      {overriddenBy && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-2.5 max-w-[86px] font-mono text-[8.5px] leading-[12px] tracking-[0.12em] text-signal/70"
        >
          {t('env.claimed')}
        </motion.p>
      )}
    </div>
  );
}
