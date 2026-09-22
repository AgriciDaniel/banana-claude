'use client';

import { useEffect, useRef } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import Lenis from 'lenis';
import { moduleById } from '@/config/modules';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { Divider, Pip } from './primitives';
import { ModulePanel } from './modules/ModulePanel';
import { useLocaleStore, useT, type TranslationKey } from '@/i18n';
import { localizeModule } from '@/i18n/modules';

/**
 * Expanded module rail.
 *
 * The card itself stays in 3D; this is the detail surface that arrives beside
 * it. Long content scrolls under Lenis rather than the browser's native
 * scroller — inertial scrolling inside a floating panel is the only thing that
 * keeps a DOM overlay feeling like part of a spatial environment instead of a
 * web page bolted to the front of one.
 */
export function ExpandedPanel() {
  const expandedId = useCarouselStore((s) => s.expandedId);
  const collapse = useCarouselStore((s) => s.collapse);
  const scroller = useRef<HTMLDivElement>(null);
  const t = useT();
  const locale = useLocaleStore((s) => s.locale);

  useEffect(() => {
    if (!expandedId || !scroller.current) return;
    const lenis = new Lenis({
      wrapper: scroller.current,
      content: scroller.current.firstElementChild as HTMLElement,
      duration: 1.05,
      easing: (t) => 1 - Math.pow(1 - t, 4),
      smoothWheel: true,
      syncTouch: true,
    });

    let raf = 0;
    const loop = (time: number) => {
      lenis.raf(time);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
    };
  }, [expandedId]);

  const mod = expandedId ? moduleById(expandedId) : undefined;
  const text = mod ? localizeModule(mod, locale) : null;

  return (
    <AnimatePresence>
      {mod && text && (
        <motion.aside
          key={mod.id}
          initial={{ opacity: 0, x: 40, filter: 'blur(10px)' }}
          animate={{ opacity: 1, x: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, x: 40, filter: 'blur(10px)' }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className="hud-panel hud-ticks pointer-events-auto absolute right-6 top-1/2 z-20 w-[330px] -translate-y-1/2 p-5"
        >
          <header className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Pip tone={mod.status === 'attention' ? 'warn' : 'good'} />
                <span className="hud-label">{t(`state.${mod.status}` as TranslationKey)}</span>
              </div>
              <h2 className="mt-2 font-sans text-[26px] font-light leading-none tracking-tight text-lumen">
                {text.name}
              </h2>
              <p className="mt-2 max-w-[240px] font-mono text-[10px] leading-[16px] tracking-[0.1em] text-ghost">
                {text.descriptor.toUpperCase()}
              </p>
            </div>
            <button
              type="button"
              onClick={collapse}
              aria-label={t('panel.collapse')}
              className="font-mono text-[10px] tracking-[0.2em] text-ghost transition-colors hover:text-ember"
            >
              ESC
            </button>
          </header>

          <Divider />

          {/*
            The module's own surface. Everything below the header is now real:
            live feeds, real charts, real links. Scrolled by Lenis so a long
            answer still feels like part of a spatial environment.
          */}
          <div ref={scroller} className="max-h-[420px] overflow-hidden">
            <div>
              <ModulePanel id={mod.id} />
            </div>
          </div>

          <Divider />

          <p className="font-mono text-[9.5px] tracking-[0.18em] text-ghost/70">
            {t('panel.collapseHint')}
          </p>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
