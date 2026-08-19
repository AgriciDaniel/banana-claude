'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import gsap from 'gsap';
import { useSystemStore } from '@/stores/useSystemStore';
import { useT } from '@/i18n';
import { LocaleSwitch } from './LocaleSwitch';

const STEPS = [
  'boot.step.render',
  'boot.step.atmosphere',
  'boot.step.physics',
  'boot.step.gesture',
  'boot.step.audio',
  'boot.step.registry',
] as const;

/**
 * Boot.
 *
 * This screen exists for a reason beyond theatre: browsers require a user
 * gesture before a microphone-adjacent permission prompt or an AudioContext
 * will do anything useful. Rather than firing a permission dialog at a cold
 * visitor, the boot sequence earns the click and then spends it on both.
 *
 * It also lets the user choose their input up front instead of being told what
 * they will be using.
 */
export function BootSequence({ onEnter }: { onEnter: (useHands: boolean) => void }) {
  const title = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0);
  const [armed, setArmed] = useState(false);
  const capabilities = useSystemStore((s) => s.capabilities);
  const t = useT();

  useEffect(() => {
    // Letter-by-letter reveal. GSAP earns its place here: a staggered timeline
    // with per-character easing is precisely what it is good at, and precisely
    // what a spring would make mushy.
    if (!title.current) return;
    const chars = title.current.querySelectorAll('[data-char]');
    const tl = gsap.timeline();
    tl.fromTo(
      chars,
      { opacity: 0, y: 26, rotateX: -60, filter: 'blur(10px)' },
      {
        opacity: 1,
        y: 0,
        rotateX: 0,
        filter: 'blur(0px)',
        duration: 1.1,
        stagger: 0.075,
        ease: 'expo.out',
      },
    );
    return () => {
      tl.kill();
    };
  }, []);

  useEffect(() => {
    // Steps tick through at a readable pace, then the entry prompt arms.
    if (step >= STEPS.length) {
      const id = window.setTimeout(() => setArmed(true), 320);
      return () => window.clearTimeout(id);
    }
    const id = window.setTimeout(() => setStep((s) => s + 1), 170 + step * 34);
    return () => window.clearTimeout(id);
  }, [step]);

  const cameraPossible = capabilities?.cameraCapable ?? false;

  return (
    <motion.div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-void"
      exit={{ opacity: 0, filter: 'blur(12px)' }}
      transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
    >
      {/* Same overhead pool of light as the scene, so the cut into 3D lands. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(120% 80% at 50% 0%, color-mix(in oklab, #2b6cff 16%, transparent) 0%, transparent 60%)',
        }}
      />

      <div ref={title} className="relative flex select-none gap-[0.14em] [perspective:800px]">
        {'NEXUS'.split('').map((c, i) => (
          <span
            key={i}
            data-char
            className="inline-block font-sans text-[13vw] font-extralight leading-none tracking-[0.06em] text-lumen sm:text-[86px]"
          >
            {c}
          </span>
        ))}
      </div>

      <p className="relative mt-3 font-mono text-[10px] tracking-[0.42em] text-ghost">
        {t('boot.subtitle')}
      </p>

      {/* Offered before anything else is read, not buried in a settings pane. */}
      <div className="relative mt-7">
        <LocaleSwitch />
      </div>

      <div className="relative mt-8 w-[300px]">
        {STEPS.map((key, i) => (
          <motion.div
            key={key}
            initial={{ opacity: 0 }}
            animate={{ opacity: i < step ? 1 : 0.18 }}
            transition={{ duration: 0.3 }}
            className="flex items-center justify-between border-b border-signal/8 py-[7px] font-mono text-[10px] tracking-[0.16em]"
          >
            <span className="text-ghost">{t(key)}</span>
            <span className={i < step ? 'text-lock' : 'text-ghost/40'}>
              {i < step ? t('boot.ok') : '——'}
            </span>
          </motion.div>
        ))}
      </div>

      <AnimatePresence>
        {armed && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
            className="relative mt-10 flex flex-col items-center gap-3"
          >
            <div className="flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => onEnter(true)}
                disabled={!cameraPossible}
                className="hud-panel hud-ticks group relative px-6 py-3 font-mono text-[11px] tracking-[0.24em] text-lumen transition-colors duration-300 hover:border-signal/45 hover:text-signal disabled:cursor-not-allowed disabled:text-ghost/50"
              >
                {t('boot.enterHands')}
              </button>
              <button
                type="button"
                onClick={() => onEnter(false)}
                className="px-4 py-3 font-mono text-[11px] tracking-[0.24em] text-ghost transition-colors duration-300 hover:text-lumen"
              >
                {t('boot.usePointer')}
              </button>
            </div>
            <p className="max-w-[340px] text-center font-mono text-[9.5px] leading-[16px] tracking-[0.12em] text-ghost/70">
              {cameraPossible ? t('boot.privacy') : t('boot.noCamera')}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
