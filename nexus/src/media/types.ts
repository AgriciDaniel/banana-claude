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

export type MediaKind = 'image' | 'video' | 'shape';

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

export interface MediaItem {
  id: string;
  kind: MediaKind;
  /** Image and video only. Always routed through /api/media. */
  src?: string;
  shape?: ShapeSpec;
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
