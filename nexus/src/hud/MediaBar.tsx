'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useMediaStore } from '@/stores/useMediaStore';
import { clearMedia } from '@/media/actions';
import { useT } from '@/i18n';

/**
 * The only chrome the display gets.
 *
 * The content itself lives in 3D; this is a caption and a way out. Anything
 * more would turn a thing standing in the room back into a window.
 */
export function MediaBar() {
  const t = useT();
  const stack = useMediaStore((s) => s.stack);
  const generating = useMediaStore((s) => s.generating);
  const error = useMediaStore((s) => s.error);

  const top = stack[0];
  const visible = Boolean(top) || generating || Boolean(error);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 12, filter: 'blur(6px)' }}
          animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
          exit={{ opacity: 0, y: 12, filter: 'blur(6px)' }}
          transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="hud-panel hud-ticks pointer-events-auto absolute left-1/2 top-6 w-[330px] max-w-[calc(100vw-56px)] -translate-x-1/2 px-3.5 py-2.5"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="hud-label">{t('media.title')}</span>
            {stack.length > 0 && (
              <button
                type="button"
                onClick={clearMedia}
                className="font-mono text-[9px] tracking-[0.2em] text-ghost transition-colors hover:text-ember"
              >
                {t('media.close')}
              </button>
            )}
          </div>

          {generating && (
            <div className="mt-2 flex items-center gap-2">
              <motion.span
                className="inline-block h-1 w-1 rounded-full bg-signal"
                animate={{ opacity: [1, 0.2, 1] }}
                transition={{ duration: 1, repeat: Infinity }}
              />
              <span className="font-mono text-[10px] tracking-[0.18em] text-signal">
                {t('media.generating')}
              </span>
            </div>
          )}

          {top && !generating && (
            <>
              <p className="mt-1.5 truncate font-sans text-[12.5px] text-lumen">
                {top.title ?? top.kind}
              </p>
              {top.caption && (
                <p className="mt-0.5 font-mono text-[9px] tracking-[0.14em] text-ghost">
                  {top.caption}
                </p>
              )}
            </>
          )}

          {error && (
            <p className="mt-1.5 font-mono text-[9.5px] leading-[15px] text-ember">{error}</p>
          )}

          {stack.length > 1 && (
            <p className="mt-1.5 font-mono text-[9px] tracking-[0.14em] text-ghost/70">
              +{stack.length - 1}
            </p>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
