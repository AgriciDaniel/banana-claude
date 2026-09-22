import { springConfig, type SpringConfig } from './Spring';

/**
 * The motion vocabulary. Named by feel, not by numbers, so a card's state
 * machine reads as intent: "focused cards use `advance`, dragged cards `lag`".
 */
export const SPRINGS = {
  /** Immediate but never harsh. Hover, small offsets. */
  crisp: springConfig(210, 26, 1),
  /** Visible overshoot then settle. Selection, expansion. */
  elastic: springConfig(190, 15, 1),
  /** Pronounced bounce — used sparingly, on expand only. */
  bouncy: springConfig(240, 12.5, 1.1),
  /** Deliberately trailing. Cards follow the hand with this. */
  lag: springConfig(88, 17, 1.35),
  /** Heavy mass, long settle. Free-flying cards returning to orbit. */
  drift: springConfig(38, 11, 2.2),
  /** Near-critical, no overshoot. Camera and anything that must not wobble. */
  glide: springConfig(64, 16, 1),
  /** Fast scalar fades — glow, opacity, border energy. */
  flash: springConfig(320, 30, 1),
  /** The ring itself: heavy, momentum-preserving, gently self-centering. */
  carousel: springConfig(52, 13.5, 1.6),
} satisfies Record<string, SpringConfig>;

export type SpringName = keyof typeof SPRINGS;
