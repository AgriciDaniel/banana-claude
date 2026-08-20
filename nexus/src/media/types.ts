/**
 * Spatial media.
 *
 * Until now NEXUS could only render what it drew itself: painted card faces,
 * particle text, procedural environments. This layer lets arbitrary content —
 * a photograph, a clip, a generated image, a parametric solid — exist as an
 * object in the room, placed and lit like everything else.
 *
 * Everything is described by data rather than by a component, so the assistant,
 * a module, or a click on a thumbnail can all request the same surface.
 */

export type MediaKind = 'image' | 'video' | 'shape' | 'chart';

/** The parametric solids the assistant can summon. */
export type ShapeKind =
  | 'sphere'
  | 'box'
  | 'torus'
  | 'knot'
  | 'icosahedron'
  | 'cylinder'
  | 'cone'
  | 'ring';

export interface ShapeSpec {
  kind: ShapeKind;
  /** Hex colour. Defaults to the active world's glow. */
  color?: string;
  /** 0.3 – 3. Relative to a ~1m object. */
  scale?: number;
  /** Turns per second. Negative reverses. */
  spin?: number;
  wireframe?: boolean;
  /** 0 = solid, 1 = fully transparent glass. */
  glass?: number;
}

/**
 * A statistic made visible.
 *
 * Charts exist so an analysis can be argued rather than asserted. The parts
 * that matter are not the bars: they are `benchmark` and `note`. A number on
 * its own tells the user where they are; a number against a reference tells
 * them whether that is good, and the note says what to do about it. Every
 * chart is expected to carry a source, because a figure with no provenance is
 * not evidence.
 */
export type ChartKind = 'bar' | 'line' | 'donut' | 'kpi' | 'funnel' | 'flow' | 'playbook';

export interface ChartPoint {
  label: string;
  value: number;
  /** Marks this point as the user's own figure among comparisons. */
  mine?: boolean;
}

export interface ChartSpec {
  kind: ChartKind;
  title: string;
  /** Where the figures came from and when. Rendered small, always shown. */
  source?: string;
  points: ChartPoint[];
  /** Appended to every value: '%', 'K', 'min', 'EUR'. */
  unit?: string;
  /** A reference value drawn across the plot -- the median, the target. */
  benchmark?: number;
  benchmarkLabel?: string;
  /** One line of "so what". This is the recommendation, not a description. */
  note?: string;
  /**
   * Playbook only: what to do on OUR subject, derived from the references
   * above. Kept separate from `points` because a playbook has two halves --
   * what works elsewhere, and the transposition -- and collapsing them into
   * one list is what turns a scenario back into a list of tips.
   */
  steps?: string[];
}

export interface MediaItem {
  id: string;
  kind: MediaKind;
  /** Image and video only. Always routed through /api/media. */
  src?: string;
  shape?: ShapeSpec;
  chart?: ChartSpec;
  title?: string;
  /** Shown small beneath the frame. Provenance, as everywhere else. */
  caption?: string;
  /** Where this came from, for the log and the HUD. */
  origin: 'assistant' | 'module' | 'generated' | 'user';
  at: number;
  /** Natural aspect ratio, filled in once the texture loads. */
  aspect?: number;
}

/** Wire format for POST /api/imagine. */
export interface ImagineRequest {
  prompt: string;
  /** 1K is plenty for a floating panel and roughly a third of the bytes. */
  size?: '1K' | '2K';
}
