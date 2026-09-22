/** The six card states. Each one owns a distinct animation signature. */
export type CardState = 'idle' | 'hovered' | 'selected' | 'expanded' | 'focused' | 'dragging';

/** Ranked so transitions can be compared (higher wins when several apply). */
export const CARD_STATE_RANK: Record<CardState, number> = {
  idle: 0,
  hovered: 1,
  focused: 2,
  selected: 3,
  dragging: 4,
  expanded: 5,
};

export type Vec3 = [number, number, number];

export type InputSource = 'hand' | 'pointer' | 'keyboard' | 'none';

export type QualityTier = 'low' | 'medium' | 'high' | 'ultra';

export type TrackingStatus = 'idle' | 'requesting' | 'loading' | 'active' | 'lost' | 'denied' | 'error';

export type BootPhase = 'cold' | 'booting' | 'ready';
