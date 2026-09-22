'use client';

import { useEffect, useRef } from 'react';
import { BONES } from '@/gesture/landmarks';
import { gestureSnapshot } from '@/stores/runtime';
import { PALETTE } from '@/config/theme';

/**
 * Diagnostic hand skeleton (press D).
 *
 * Draws the raw landmark solution over the scene. Kept out of the default view
 * because the reticle is the real affordance — but when tracking misbehaves,
 * seeing the actual skeleton is the difference between a five-minute fix and
 * an afternoon of guessing.
 */
export function HandOverlay({ visible }: { visible: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!visible) return;
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      el.width = window.innerWidth * dpr;
      el.height = window.innerHeight * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener('resize', resize);

    const draw = () => {
      raf = requestAnimationFrame(draw);
      const w = window.innerWidth;
      const h = window.innerHeight;
      ctx.clearRect(0, 0, w, h);

      for (const hand of gestureSnapshot.hands) {
        const l = hand.landmarks;
        const px = (i: number) => l[i * 3] * w;
        const py = (i: number) => l[i * 3 + 1] * h;

        ctx.strokeStyle = hand.pinch > 0.6 ? PALETTE.lock : PALETTE.signal;
        ctx.lineWidth = 1.5;
        ctx.globalAlpha = 0.55;
        ctx.beginPath();
        for (const [a, b] of BONES) {
          ctx.moveTo(px(a), py(a));
          ctx.lineTo(px(b), py(b));
        }
        ctx.stroke();

        ctx.globalAlpha = 0.95;
        ctx.fillStyle = PALETTE.lumen;
        for (let i = 0; i < 21; i++) {
          ctx.beginPath();
          ctx.arc(px(i), py(i), i === 4 || i === 8 ? 4 : 2, 0, Math.PI * 2);
          ctx.fill();
        }

        // Pinch span, annotated.
        ctx.globalAlpha = 0.8;
        ctx.strokeStyle = hand.pinch > 0.6 ? PALETTE.lock : PALETTE.ember;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(px(4), py(4));
        ctx.lineTo(px(8), py(8));
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillStyle = PALETTE.ghost;
        ctx.font = '10px ui-monospace, monospace';
        ctx.fillText(
          `${hand.handedness.toUpperCase()} · PINCH ${hand.pinch.toFixed(2)} · OPEN ${hand.openness.toFixed(2)} · D ${hand.depth.toFixed(2)}`,
          px(0) + 12,
          py(0) + 4,
        );
      }
      ctx.globalAlpha = 1;
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, [visible]);

  if (!visible) return null;
  return <canvas ref={canvas} className="pointer-events-none fixed inset-0 z-30" />;
}
