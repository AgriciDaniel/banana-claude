/**
 * Text -> particle targets.
 *
 * Rasterises a paragraph to an offscreen canvas and returns the lit pixels as
 * world-space points. The sampling step adapts to the amount of text, so a long
 * answer stays inside the particle budget instead of thinning out into
 * illegibility or blowing past the buffer.
 */

/*
 * Raster resolution is chosen to MATCH the particle budget, and that coupling
 * is the whole trick.
 *
 * The first version rasterised at 1100px wide with a 40px font. Two lines of
 * that produce far more lit pixels than there are particles, so the sampler
 * backed off to every 5th or 6th pixel - wider than the glyph strokes
 * themselves - and the result was a faint dotted smudge rather than text.
 *
 * At this resolution a two-line answer lands near 1000 samples at a step of 2,
 * which is dense enough that neighbouring particles overlap into continuous
 * strokes. A heavier weight keeps stems at least three pixels wide so they
 * survive the sampling.
 */
const CANVAS_W = 620;
const CANVAS_H = 230;
const LINE_H = 34;
const PADDING = 10;

export interface RasterResult {
  /** Flat xy pairs in world units, centred on the origin. */
  points: Float32Array;
  count: number;
  /** Reading order index per point, 0..1 — drives the assembly stagger. */
  order: Float32Array;
  /** Height of the laid-out block in world units, for vertical centring. */
  height: number;
  /**
   * Spacing between sampled pixels, in world units. The renderer sizes each
   * particle from this so glyph strokes stay connected at any density.
   */
  spacing: number;
}

let canvas: HTMLCanvasElement | null = null;
let ctx: CanvasRenderingContext2D | null = null;

function surface(): CanvasRenderingContext2D | null {
  if (ctx) return ctx;
  if (typeof document === 'undefined') return null;
  canvas = document.createElement('canvas');
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;
  ctx = canvas.getContext('2d', { willReadFrequently: true });
  return ctx;
}

const FONT = '600 26px Inter, system-ui, -apple-system, "Segoe UI", sans-serif';

/**
 * @param text     the paragraph to lay out
 * @param width    target width in world units
 * @param budget   maximum number of points to return
 */
export function rasterise(text: string, width: number, budget: number): RasterResult {
  const empty: RasterResult = {
    points: new Float32Array(0),
    count: 0,
    order: new Float32Array(0),
    height: 0,
    spacing: 0,
  };

  const c = surface();
  if (!c || !text.trim()) return empty;

  c.clearRect(0, 0, CANVAS_W, CANVAS_H);
  c.font = FONT;
  c.textBaseline = 'top';
  c.fillStyle = '#ffffff';

  // --- wrap -------------------------------------------------------------
  const maxLineWidth = CANVAS_W - PADDING * 2;
  const words = text.replace(/\s+/g, ' ').trim().split(' ');
  const lines: string[] = [];
  let line = '';
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (c.measureText(candidate).width > maxLineWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line);

  // Keep the most recent lines: a long answer scrolls upward out of the panel
  // rather than shrinking to fit, which would make earlier text unreadable.
  const maxLines = Math.floor((CANVAS_H - PADDING * 2) / LINE_H);
  const visible = lines.slice(-maxLines);
  if (visible.length === 0) return empty;

  for (let i = 0; i < visible.length; i++) {
    c.fillText(visible[i]!, PADDING, PADDING + i * LINE_H);
  }

  // --- sample -----------------------------------------------------------
  const blockH = visible.length * LINE_H;
  const image = c.getImageData(0, 0, CANVAS_W, PADDING * 2 + blockH);
  const data = image.data;
  const imgH = image.height;

  // Estimate density once, then choose a step that lands near the budget.
  let step = 2;
  let count = countLit(data, CANVAS_W, imgH, step);
  while (count > budget && step < 6) {
    step += 1;
    count = countLit(data, CANVAS_W, imgH, step);
  }
  if (count === 0) return empty;

  const scale = width / CANVAS_W;
  const height = imgH * scale;

  const points = new Float32Array(count * 2);
  const order = new Float32Array(count);
  let n = 0;

  // Column-major so `order` increases left-to-right: particles land in
  // reading order, which is what makes it look like writing rather than
  // like a texture fading in.
  for (let x = 0; x < CANVAS_W; x += step) {
    for (let y = 0; y < imgH; y += step) {
      if (data[(y * CANVAS_W + x) * 4 + 3]! < 128) continue;
      if (n >= count) break;
      points[n * 2] = (x - CANVAS_W / 2) * scale;
      points[n * 2 + 1] = (imgH / 2 - y) * scale;
      order[n] = x / CANVAS_W;
      n++;
    }
  }

  return { points, count: n, order, height, spacing: step * scale };
}

function countLit(data: Uint8ClampedArray, w: number, h: number, step: number): number {
  let n = 0;
  for (let x = 0; x < w; x += step) {
    for (let y = 0; y < h; y += step) {
      if (data[(y * w + x) * 4 + 3]! >= 128) n++;
    }
  }
  return n;
}
