import { CanvasTexture, SRGBColorSpace, type Texture } from 'three';
import { PALETTE } from '@/config/theme';
import type { ChartSpec } from '@/media/types';

/**
 * Statistics, painted.
 *
 * Charts are drawn to a canvas and used as a texture for the same reason the
 * card faces are: painted pixels travel through the bloom and the refraction
 * with everything else, so a bar chart is lit by the room instead of floating
 * on top of it. HTML overlaid on the canvas would always look pasted on.
 *
 * Reveal is quantised. Repainting a 1024x640 canvas every frame costs more
 * than the whole scene does -- the music card taught that at twelve frames a
 * second -- so progress is rounded to a fixed number of steps and the texture
 * is only redrawn when the step changes.
 */

const W = 1024;
const H = 640;
const PAD = 56;
const MONO = 'ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Mono", Menlo, monospace';
const SANS = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

/** Reveal steps: enough that growth reads as motion, few enough to be cheap. */
export const REVEAL_STEPS = 24;

const cache = new Map<string, Texture>();
const CACHE_LIMIT = 32;

export function getChartTexture(spec: ChartSpec, revealStep: number): Texture {
  const key = `${JSON.stringify(spec)}:${revealStep}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const tex = paint(spec, revealStep / REVEAL_STEPS);
  cache.set(key, tex);
  if (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) {
      cache.get(oldest)?.dispose();
      cache.delete(oldest);
    }
  }
  return tex;
}

export function disposeChartTextures(): void {
  for (const tex of cache.values()) tex.dispose();
  cache.clear();
}

interface Plot {
  x: number;
  y: number;
  w: number;
  h: number;
}

function paint(spec: ChartSpec, reveal: number): Texture {
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  ground(ctx);
  const top = header(ctx, spec);
  const footTop = footer(ctx, spec);
  const plot: Plot = { x: PAD, y: top, w: W - PAD * 2, h: footTop - top - 24 };

  if (spec.kind === 'bar') bars(ctx, spec, plot, reveal);
  else if (spec.kind === 'line') line(ctx, spec, plot, reveal);
  else if (spec.kind === 'donut') donut(ctx, spec, plot, reveal);
  else if (spec.kind === 'funnel') funnel(ctx, spec, plot, reveal);
  else if (spec.kind === 'flow') flow(ctx, spec, plot, reveal);
  else if (spec.kind === 'playbook') playbook(ctx, spec, plot, reveal);
  else if (spec.kind === 'plan') plan(ctx, spec, plot, reveal);
  else if (spec.kind === 'profile') profile(ctx, spec, plot, reveal);
  else if (spec.kind === 'heatmap') heatmap(ctx, spec, plot, reveal);
  else kpi(ctx, spec, plot, reveal);

  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function ground(ctx: CanvasRenderingContext2D) {
  const g = ctx.createLinearGradient(0, 0, W * 0.5, H);
  g.addColorStop(0, '#0A1220');
  g.addColorStop(1, '#050A12');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = 'rgba(99,201,255,0.07)';
  ctx.lineWidth = 1;
  for (let x = PAD; x < W - PAD; x += 64) {
    ctx.beginPath();
    ctx.moveTo(x + 0.5, 0);
    ctx.lineTo(x + 0.5, H);
    ctx.stroke();
  }
}

function header(ctx: CanvasRenderingContext2D, spec: ChartSpec): number {
  ctx.fillStyle = PALETTE.lumen;
  ctx.font = `600 36px ${SANS}`;
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(clip(ctx, spec.title, W - PAD * 2), PAD, PAD + 34);

  ctx.fillStyle = PALETTE.signal;
  ctx.fillRect(PAD, PAD + 52, 54, 3);
  return PAD + 100;
}

/**
 * Source and recommendation sit at the bottom; returns where they begin.
 *
 * The note is drawn in the confirmation colour and led by a caret, so it reads
 * as advice rather than as a caption. It is the point of the chart.
 */
function footer(ctx: CanvasRenderingContext2D, spec: ChartSpec): number {
  let y = H - PAD;

  if (spec.source) {
    ctx.fillStyle = PALETTE.ghost;
    ctx.font = `500 19px ${MONO}`;
    ctx.fillText(clip(ctx, spec.source.toUpperCase(), W - PAD * 2), PAD, y);
    y -= 36;
  }

  if (spec.note) {
    ctx.font = `600 23px ${SANS}`;
    const lines = wrap(ctx, spec.note, W - PAD * 2 - 34).slice(0, 2);
    ctx.fillStyle = PALETTE.lock;
    for (let i = lines.length - 1; i >= 0; i--) {
      ctx.fillText(lines[i]!, PAD + 32, y);
      y -= 32;
    }
    ctx.beginPath();
    ctx.moveTo(PAD + 6, y + 20);
    ctx.lineTo(PAD + 20, y + 28);
    ctx.lineTo(PAD + 6, y + 36);
    ctx.fill();
    y -= 10;
  }

  return y;
}

/** Headroom above the tallest thing on the plot, benchmark included. */
function scale(spec: ChartSpec): number {
  const top = Math.max(
    ...spec.points.map((p) => p.value),
    spec.benchmark ?? Number.NEGATIVE_INFINITY,
  );
  return top <= 0 ? 1 : top * 1.12;
}

function bars(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const n = spec.points.length;
  if (n === 0) return;
  const max = scale(spec);
  const gap = 16;
  const rowH = Math.min(62, (plot.h - gap * (n - 1)) / n);
  const labelW = 220;
  const trackX = plot.x + labelW;
  const trackW = plot.w - labelW - 104;

  spec.points.forEach((point, i) => {
    const y = plot.y + i * (rowH + gap);
    const mine = point.mine === true;

    ctx.fillStyle = mine ? PALETTE.lumen : PALETTE.ghost;
    ctx.font = `${mine ? 600 : 500} 22px ${SANS}`;
    ctx.fillText(clip(ctx, point.label, labelW - 18), plot.x, y + rowH / 2 + 8);

    ctx.fillStyle = 'rgba(99,201,255,0.08)';
    ctx.fillRect(trackX, y, trackW, rowH);

    const w = Math.max(0, (point.value / max) * trackW * reveal);
    const grad = ctx.createLinearGradient(trackX, 0, trackX + trackW, 0);
    grad.addColorStop(0, mine ? PALETTE.signal : 'rgba(99,201,255,0.34)');
    grad.addColorStop(1, mine ? PALETTE.core : 'rgba(43,108,255,0.28)');
    ctx.fillStyle = grad;
    ctx.fillRect(trackX, y, w, rowH);

    if (mine && w > 3) {
      ctx.fillStyle = PALETTE.signal;
      ctx.fillRect(trackX + w - 3, y, 3, rowH);
    }

    ctx.fillStyle = mine ? PALETTE.lumen : PALETTE.ghost;
    ctx.font = `600 24px ${MONO}`;
    ctx.fillText(format(point.value * reveal, spec.unit), trackX + trackW + 18, y + rowH / 2 + 9);
  });

  if (spec.benchmark !== undefined) {
    const x = trackX + (spec.benchmark / max) * trackW;
    rule(ctx, x, plot.y - 16, plot.y + n * (rowH + gap) - gap + 10, spec.benchmarkLabel);
  }
}

/** The reference line. Ember, because it is the only mark here that judges. */
function rule(
  ctx: CanvasRenderingContext2D,
  x: number,
  top: number,
  bottom: number,
  label?: string,
) {
  ctx.save();
  ctx.strokeStyle = PALETTE.ember;
  ctx.lineWidth = 2;
  ctx.setLineDash([7, 7]);
  ctx.beginPath();
  ctx.moveTo(x, top);
  ctx.lineTo(x, bottom);
  ctx.stroke();
  ctx.restore();

  if (!label) return;
  ctx.fillStyle = PALETTE.ember;
  ctx.font = `600 18px ${MONO}`;
  const text = label.toUpperCase();
  const w = ctx.measureText(text).width;
  ctx.fillText(text, Math.min(x + 10, W - PAD - w), top + 2);
}

function line(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const pts = spec.points;
  if (pts.length < 2) return;
  const max = scale(spec);
  const stepX = plot.w / (pts.length - 1);
  const at = (i: number) => ({
    x: plot.x + i * stepX,
    y: plot.y + plot.h - (pts[i]!.value / max) * plot.h,
  });

  const shown = Math.max(1, Math.floor(1 + (pts.length - 1) * reveal));

  ctx.beginPath();
  ctx.moveTo(plot.x, plot.y + plot.h);
  for (let i = 0; i < shown; i++) {
    const p = at(i);
    ctx.lineTo(p.x, p.y);
  }
  const edge = at(shown - 1);
  ctx.lineTo(edge.x, plot.y + plot.h);
  ctx.closePath();
  const fill = ctx.createLinearGradient(0, plot.y, 0, plot.y + plot.h);
  fill.addColorStop(0, 'rgba(99,201,255,0.30)');
  fill.addColorStop(1, 'rgba(99,201,255,0.02)');
  ctx.fillStyle = fill;
  ctx.fill();

  ctx.strokeStyle = PALETTE.signal;
  ctx.lineWidth = 3;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  for (let i = 0; i < shown; i++) {
    const p = at(i);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();

  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `500 18px ${MONO}`;
  const every = Math.ceil(pts.length / 6);
  pts.forEach((p, i) => {
    if (i % every !== 0 && i !== pts.length - 1) return;
    const text = p.label.toUpperCase();
    const w = ctx.measureText(text).width;
    const x = Math.max(plot.x, Math.min(plot.x + i * stepX - w / 2, W - PAD - w));
    ctx.fillText(text, x, plot.y + plot.h + 30);
  });

  if (spec.benchmark !== undefined) {
    const y = plot.y + plot.h - (spec.benchmark / max) * plot.h;
    ctx.save();
    ctx.strokeStyle = PALETTE.ember;
    ctx.lineWidth = 2;
    ctx.setLineDash([7, 7]);
    ctx.beginPath();
    ctx.moveTo(plot.x, y);
    ctx.lineTo(plot.x + plot.w, y);
    ctx.stroke();
    ctx.restore();
    if (spec.benchmarkLabel) {
      ctx.fillStyle = PALETTE.ember;
      ctx.font = `600 18px ${MONO}`;
      ctx.fillText(spec.benchmarkLabel.toUpperCase(), plot.x, y - 12);
    }
  }

  const last = pts[shown - 1]!;
  ctx.fillStyle = PALETTE.lumen;
  ctx.font = `600 34px ${MONO}`;
  ctx.fillText(format(last.value, spec.unit), plot.x, plot.y - 20);
}

function donut(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const total = spec.points.reduce((sum, p) => sum + p.value, 0) || 1;
  const cx = plot.x + plot.w * 0.26;
  const cy = plot.y + plot.h / 2;
  const r = Math.min(plot.h / 2 - 10, 128);
  const shades = [PALETTE.signal, PALETTE.core, PALETTE.lock, PALETTE.ghost];

  let angle = -Math.PI / 2;
  spec.points.forEach((p, i) => {
    const sweep = (p.value / total) * Math.PI * 2 * reveal;
    ctx.beginPath();
    ctx.arc(cx, cy, r, angle, angle + sweep);
    ctx.strokeStyle = p.mine ? PALETTE.signal : shades[i % shades.length]!;
    ctx.lineWidth = p.mine ? 42 : 34;
    ctx.stroke();
    angle += sweep;
  });

  const legendX = plot.x + plot.w * 0.54;
  spec.points.forEach((p, i) => {
    const y = cy - (spec.points.length - 1) * 22 + i * 44;
    ctx.fillStyle = p.mine ? PALETTE.signal : shades[i % shades.length]!;
    ctx.fillRect(legendX, y - 13, 14, 14);
    ctx.fillStyle = p.mine ? PALETTE.lumen : PALETTE.ghost;
    ctx.font = `${p.mine ? 600 : 500} 22px ${SANS}`;
    ctx.fillText(clip(ctx, p.label, 250), legendX + 26, y);
    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `600 22px ${MONO}`;
    ctx.fillText(format((p.value / total) * 100 * reveal, '%'), legendX + 296, y);
  });
}

function kpi(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const main = spec.points[0];
  if (!main) return;
  const cy = plot.y + plot.h / 2;

  if (spec.benchmark !== undefined) {
    const delta = main.value - spec.benchmark;
    const ahead = delta >= 0;
    ctx.fillStyle = ahead ? PALETTE.lock : PALETTE.ember;
    ctx.font = `600 30px ${MONO}`;
    const text = `${ahead ? '+' : ''}${format(delta, spec.unit)} ${spec.benchmarkLabel ?? ''}`;
    ctx.fillText(text.trim().toUpperCase(), plot.x, cy - 92);
  }

  ctx.fillStyle = PALETTE.lumen;
  ctx.font = `700 130px ${MONO}`;
  ctx.fillText(format(main.value * reveal, spec.unit), plot.x, cy + 26);

  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `500 24px ${SANS}`;
  ctx.fillText(clip(ctx, main.label, plot.w), plot.x, cy + 68);
}

function format(value: number, unit?: string): string {
  const abs = Math.abs(value);
  let text: string;
  if (abs >= 1_000_000) text = `${(value / 1_000_000).toFixed(1)}M`;
  else if (abs >= 10_000) text = `${(value / 1000).toFixed(0)}K`;
  else if (abs >= 100) text = value.toFixed(0);
  // A count is a whole thing. "51.0 abonnes" reads as a measurement error.
  else if (Number.isInteger(value)) text = String(value);
  else if (abs >= 10) text = value.toFixed(1);
  else text = value.toFixed(abs < 1 ? 2 : 1);
  return unit ? (unit === '%' ? `${text}%` : `${text} ${unit}`) : text;
}

function clip(ctx: CanvasRenderingContext2D, text: string, max: number): string {
  if (ctx.measureText(text).width <= max) return text;
  let out = text;
  while (out.length > 1 && ctx.measureText(`${out}...`).width > max) out = out.slice(0, -1);
  return `${out}...`;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, max: number): string[] {
  const words = text.split(' ');
  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (ctx.measureText(next).width > max && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines;
}

/**
 * A funnel: the same quantity surviving successive stages.
 *
 * Drawn as stacked trapezoids whose width is the value, so the shape itself
 * carries the argument -- a narrow waist is visible before any number is read.
 * The drop between stages is labelled, because the interesting figure in a
 * funnel is never a stage, it is a loss.
 */
function funnel(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const pts = spec.points;
  if (pts.length < 2) return;
  const top = Math.max(...pts.map((p) => p.value)) || 1;
  const rowH = Math.min(78, plot.h / pts.length);
  const maxW = plot.w * 0.52;
  const cx = plot.x + maxW / 2 + 30;

  /*
   * A real funnel spans orders of magnitude -- twelve thousand impressions
   * against twelve follows -- and a strictly proportional width turns the last
   * stages into invisible threads. The floor keeps every stage readable while
   * the ordering and the labelled drops carry the actual proportions.
   */
  const FLOOR = 0.15;
  const widthAt = (i: number) => (FLOOR + (1 - FLOOR) * (pts[i]!.value / top)) * maxW;

  pts.forEach((p, i) => {
    const y = plot.y + i * rowH;
    const grown = Math.min(1, Math.max(0, reveal * pts.length - i));
    const wTop = widthAt(i) * grown;
    const wBottom = (i + 1 < pts.length ? widthAt(i + 1) : widthAt(i) * 0.82) * grown;

    ctx.beginPath();
    ctx.moveTo(cx - wTop / 2, y);
    ctx.lineTo(cx + wTop / 2, y);
    ctx.lineTo(cx + wBottom / 2, y + rowH - 8);
    ctx.lineTo(cx - wBottom / 2, y + rowH - 8);
    ctx.closePath();
    const g = ctx.createLinearGradient(cx - wTop / 2, 0, cx + wTop / 2, 0);
    const fade = 1 - i * 0.13;
    g.addColorStop(0, p.mine ? PALETTE.signal : `rgba(99,201,255,${0.42 * fade})`);
    g.addColorStop(1, p.mine ? PALETTE.core : `rgba(43,108,255,${0.34 * fade})`);
    ctx.fillStyle = g;
    ctx.fill();

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `600 22px ${SANS}`;
    ctx.fillText(clip(ctx, p.label, plot.w * 0.4), plot.x + maxW + 78, y + rowH / 2);

    ctx.fillStyle = p.mine ? PALETTE.signal : PALETTE.ghost;
    ctx.font = `600 22px ${MONO}`;
    ctx.fillText(format(p.value, spec.unit), plot.x + maxW + 78, y + rowH / 2 + 28);

    // The loss into the next stage, which is the number worth acting on.
    if (i + 1 < pts.length && pts[i]!.value > 0) {
      const kept = (pts[i + 1]!.value / pts[i]!.value) * 100;
      const weak = kept < 40;
      ctx.fillStyle = weak ? PALETTE.ember : PALETTE.lock;
      ctx.font = `600 19px ${MONO}`;
      const text = `-${(100 - kept).toFixed(0)}%`;
      const w = ctx.measureText(text).width;
      ctx.fillText(text, cx - w / 2, y + rowH + 2);
    }
  });
}

/**
 * A flow: ordered steps with arrows between them. No quantities -- this is for
 * explaining a sequence, which is a different job from measuring one.
 */
function flow(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const pts = spec.points;
  if (pts.length === 0) return;
  const n = Math.min(pts.length, 5);
  const gap = 28;
  const boxW = (plot.w - gap * (n - 1)) / n;
  const boxH = Math.min(150, plot.h * 0.62);
  const y = plot.y + (plot.h - boxH) / 2;

  for (let i = 0; i < n; i++) {
    const p = pts[i]!;
    const shown = Math.min(1, Math.max(0, reveal * n - i));
    if (shown <= 0) continue;
    const x = plot.x + i * (boxW + gap);

    ctx.globalAlpha = shown;
    ctx.fillStyle = p.mine ? 'rgba(99,201,255,0.20)' : 'rgba(99,201,255,0.07)';
    round(ctx, x, y, boxW, boxH, 14);
    ctx.fill();
    ctx.strokeStyle = p.mine ? PALETTE.signal : 'rgba(99,201,255,0.28)';
    ctx.lineWidth = p.mine ? 3 : 1.5;
    round(ctx, x, y, boxW, boxH, 14);
    ctx.stroke();

    ctx.fillStyle = PALETTE.ghost;
    ctx.font = `600 18px ${MONO}`;
    ctx.fillText(`0${i + 1}`, x + 20, y + 36);

    ctx.fillStyle = p.mine ? PALETTE.lumen : PALETTE.ghost;
    ctx.font = `600 22px ${SANS}`;
    const lines = wrap(ctx, p.label, boxW - 40).slice(0, 3);
    lines.forEach((text, k) => ctx.fillText(text, x + 20, y + 76 + k * 28));

    if (i < n - 1) {
      const ax = x + boxW + gap / 2;
      const ay = y + boxH / 2;
      ctx.strokeStyle = PALETTE.signal;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(ax - 9, ay);
      ctx.lineTo(ax + 5, ay);
      ctx.stroke();
      ctx.fillStyle = PALETTE.signal;
      ctx.beginPath();
      ctx.moveTo(ax + 4, ay - 6);
      ctx.lineTo(ax + 12, ay);
      ctx.lineTo(ax + 4, ay + 6);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
}

function round(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/**
 * A playbook: what works elsewhere, and what we do about it.
 *
 * The layout is an argument in two halves. On the left, real channels with
 * the figure that earns them a place -- these must be measured, never
 * remembered. On the right, the transposition onto the user's own subject.
 * The divider between them is the whole point: it is where imitation becomes
 * adaptation, and drawing it makes the distinction impossible to skip.
 */
function playbook(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const midX = plot.x + plot.w * 0.46;
  const refs = spec.points.slice(0, 3);
  const steps = (spec.steps ?? []).slice(0, 4);

  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `600 18px ${MONO}`;
  ctx.fillText('CE QUI MARCHE', plot.x, plot.y - 6);
  ctx.fillText('SUR NOS SUJETS', midX + 46, plot.y - 6);

  ctx.save();
  ctx.strokeStyle = 'rgba(99,201,255,0.22)';
  ctx.lineWidth = 1;
  ctx.setLineDash([5, 9]);
  ctx.beginPath();
  ctx.moveTo(midX + 14, plot.y - 26);
  ctx.lineTo(midX + 14, plot.y + plot.h);
  ctx.stroke();
  ctx.restore();

  refs.forEach((ref, i) => {
    const shown = Math.min(1, Math.max(0, reveal * 2 - i * 0.2));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const y = plot.y + 34 + i * 74;

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `600 24px ${SANS}`;
    ctx.fillText(clip(ctx, ref.label, plot.w * 0.4), plot.x, y);

    ctx.fillStyle = PALETTE.signal;
    ctx.font = `600 22px ${MONO}`;
    ctx.fillText(format(ref.value, spec.unit), plot.x, y + 30);
    ctx.globalAlpha = 1;
  });

  steps.forEach((step, i) => {
    const shown = Math.min(1, Math.max(0, reveal * 2 - 0.6 - i * 0.15));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const y = plot.y + 30 + i * 56;
    const x = midX + 46;

    ctx.fillStyle = PALETTE.lock;
    ctx.beginPath();
    ctx.arc(x - 20, y - 7, 4.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `500 22px ${SANS}`;
    const lines = wrap(ctx, step, plot.w - (x - plot.x) - 10).slice(0, 2);
    lines.forEach((text, k) => ctx.fillText(text, x, y + k * 26));
    ctx.globalAlpha = 1;
  });
}

/**
 * A plan: what to do, in what order, and what proves it worked.
 *
 * Laid out along a spine because sequence is the substance of a plan -- the
 * same four actions in the wrong order is a different and usually worse plan.
 * Each point's value is its horizon, so "2" means the second week; the labels
 * carry the action itself.
 *
 * The target sits at the end of the spine, as a from/to. A plan whose result
 * cannot be checked is a wish list, and the next conversation is precisely
 * where that check has to be possible.
 */
function plan(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const steps = spec.points.slice(0, 5);
  if (steps.length === 0) return;

  const spineY = plot.y + 46;
  const usable = spec.target ? plot.w - 230 : plot.w;
  const gap = usable / steps.length;

  ctx.strokeStyle = 'rgba(99,201,255,0.24)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(plot.x, spineY);
  ctx.lineTo(plot.x + usable * Math.min(1, reveal * 1.2), spineY);
  ctx.stroke();

  steps.forEach((step, i) => {
    const shown = Math.min(1, Math.max(0, reveal * steps.length - i));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const x = plot.x + i * gap + 8;

    ctx.fillStyle = PALETTE.signal;
    ctx.beginPath();
    ctx.arc(x, spineY, 7, 0, Math.PI * 2);
    ctx.fill();

    // The horizon, which is the half of a plan people skip.
    ctx.fillStyle = PALETTE.ember;
    ctx.font = `600 17px ${MONO}`;
    const when = step.value > 0 ? `S${Math.round(step.value)}` : 'MAINTENANT';
    ctx.fillText(when, x - 4, spineY - 20);

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `500 20px ${SANS}`;
    // Six lines at this width fits an action written as a full instruction,
    // which is the only kind worth putting on a plan.
    const lines = wrap(ctx, step.label, gap - 22).slice(0, 6);
    lines.forEach((text, k) => ctx.fillText(text, x - 4, spineY + 38 + k * 25));
    ctx.globalAlpha = 1;
  });

  if (!spec.target) return;

  const boxX = plot.x + usable + 26;
  const boxW = plot.w - usable - 26;
  ctx.fillStyle = 'rgba(79,224,196,0.08)';
  round(ctx, boxX, spineY - 34, boxW, 128, 12);
  ctx.fill();
  ctx.strokeStyle = 'rgba(79,224,196,0.35)';
  ctx.lineWidth = 1.5;
  round(ctx, boxX, spineY - 34, boxW, 128, 12);
  ctx.stroke();

  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `600 16px ${MONO}`;
  ctx.fillText('CE QUI DOIT BOUGER', boxX + 16, spineY - 12);

  ctx.fillStyle = PALETTE.lumen;
  ctx.font = `500 19px ${SANS}`;
  ctx.fillText(clip(ctx, spec.target.metric, boxW - 32), boxX + 16, spineY + 14);

  /*
   * The unit is written once, on the destination. Repeating it on both sides
   * doubled the width of the line for no added meaning, and "51 abo > 250 ab"
   * -- clipped mid-word at the box edge -- is worse than either.
   */
  const from = format(spec.target.from);
  const to = format(spec.target.to, spec.target.unit);
  const arrow = ' › ';

  // Shrink to fit rather than clip: this line is the promise being made.
  let size = 30;
  do {
    ctx.font = `700 ${size}px ${MONO}`;
    if (ctx.measureText(from + arrow + to).width <= boxW - 32) break;
    size -= 2;
  } while (size > 18);

  ctx.fillStyle = PALETTE.ghost;
  ctx.fillText(from, boxX + 16, spineY + 56);
  const fromW = ctx.measureText(from).width;

  ctx.fillStyle = PALETTE.lock;
  ctx.fillText(arrow + to, boxX + 16 + fromW, spineY + 56);
}

/**
 * A profile: who or what this is, and what it has done.
 *
 * The companion to a photograph. Showing a face answers "which one" and
 * nothing else; the questions that follow are always what they play, where,
 * and what they have won. Facts run down the left as label and value, honours
 * down the right, because those are two different kinds of claim and mixing
 * them into one list makes both harder to scan.
 */
function profile(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const strengths = (spec.strengths ?? []).slice(0, 3);
  const weaknesses = (spec.weaknesses ?? []).slice(0, 3);
  const judged = strengths.length + weaknesses.length > 0;

  /*
   * The record above, the reading below, with a rule between them. The line is
   * the honest part of this layout: everything over it was fetched, everything
   * under it is an opinion, and the panel should not let the second borrow the
   * authority of the first.
   */
  /*
   * The record's height is measured from what it holds, not taken as a
   * fraction of the panel. A fixed share let a fourth fact run straight
   * through the heading of the band below it.
   */
  const FACT_STEP = 48;
  const JUDGED_STEP = 40;
  // Heading, then one row per line. The rule above the band is its own
  // separation, so no further gap is reserved on top of this.
  const assessH = judged ? 34 + Math.max(strengths.length, weaknesses.length) * JUDGED_STEP : 0;

  const room = plot.h - assessH;
  const maxRows = Math.max(1, Math.floor((room - 34) / FACT_STEP) + 1);

  const facts = (spec.facts ?? []).slice(0, Math.min(6, maxRows));
  const honours = (spec.steps ?? []).slice(0, Math.min(6, maxRows));
  const recordH = 30 + Math.max(facts.length, honours.length) * FACT_STEP;
  const split = honours.length > 0 ? plot.x + plot.w * 0.46 : plot.x + plot.w;

  if (honours.length > 0) {
    ctx.save();
    ctx.strokeStyle = 'rgba(99,201,255,0.18)';
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 9]);
    ctx.beginPath();
    ctx.moveTo(split + 16, plot.y - 18);
    ctx.lineTo(split + 16, plot.y + recordH - 14);
    ctx.stroke();
    ctx.restore();
  }

  facts.forEach((fact, i) => {
    const shown = Math.min(1, Math.max(0, reveal * 2 - i * 0.12));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const y = plot.y + 22 + i * FACT_STEP;

    ctx.fillStyle = PALETTE.ghost;
    ctx.font = `500 17px ${MONO}`;
    ctx.fillText(clip(ctx, fact.label.toUpperCase(), split - plot.x - 20), plot.x, y);

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `600 24px ${SANS}`;
    ctx.fillText(clip(ctx, fact.value, split - plot.x - 20), plot.x, y + 27);
    ctx.globalAlpha = 1;
  });

  if (judged) assessment(ctx, spec, plot, plot.y + recordH + 22, reveal);

  if (honours.length === 0) return;

  const x = split + 46;
  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `600 17px ${MONO}`;
  ctx.fillText('PALMARES', x, plot.y - 18);

  honours.forEach((line, i) => {
    const shown = Math.min(1, Math.max(0, reveal * 2 - 0.3 - i * 0.12));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const y = plot.y + 22 + i * FACT_STEP;

    ctx.fillStyle = PALETTE.lock;
    ctx.beginPath();
    ctx.arc(x - 20, y - 7, 4.5, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = PALETTE.lumen;
    ctx.font = `500 21px ${SANS}`;
    const lines = wrap(ctx, line, plot.w - (x - plot.x) - 10).slice(0, 2);
    lines.forEach((text, k) => ctx.fillText(text, x, y + k * 24));
    ctx.globalAlpha = 1;
  });
}

/** The reading: what is strong, what is not, drawn below the record. */
function assessment(
  ctx: CanvasRenderingContext2D,
  spec: ChartSpec,
  plot: Plot,
  top: number,
  reveal: number,
) {
  const strengths = (spec.strengths ?? []).slice(0, 3);
  const weaknesses = (spec.weaknesses ?? []).slice(0, 3);
  if (strengths.length + weaknesses.length === 0) return;

  ctx.save();
  ctx.strokeStyle = 'rgba(99,201,255,0.16)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(plot.x, top - 26);
  ctx.lineTo(plot.x + plot.w, top - 26);
  ctx.stroke();
  ctx.restore();

  const half = plot.w / 2;
  const columns: Array<{ title: string; lines: string[]; colour: string; x: number }> = [
    { title: 'POINTS FORTS', lines: strengths, colour: PALETTE.lock, x: plot.x },
    { title: 'LIMITES', lines: weaknesses, colour: PALETTE.ember, x: plot.x + half },
  ];

  for (const column of columns) {
    if (column.lines.length === 0) continue;

    ctx.fillStyle = PALETTE.ghost;
    ctx.font = `600 16px ${MONO}`;
    ctx.fillText(column.title, column.x, top);

    column.lines.forEach((line, i) => {
      const shown = Math.min(1, Math.max(0, reveal * 2 - 0.8 - i * 0.1));
      if (shown <= 0) return;
      ctx.globalAlpha = shown;
      const y = top + 30 + i * 40;

      ctx.fillStyle = column.colour;
      ctx.fillRect(column.x, y - 11, 3, 14);

      ctx.fillStyle = PALETTE.lumen;
      ctx.font = `500 19px ${SANS}`;
      const wrapped = wrap(ctx, line, half - 34).slice(0, 2);
      wrapped.forEach((text, k) => ctx.fillText(text, column.x + 14, y + k * 21));
      ctx.globalAlpha = 1;
    });
  }
}

/**
 * A comparative heatmap: several subjects, several metrics, one glance.
 *
 * Two colourings, and the choice between them is the substance of the form.
 *
 * Without `expected`, a cell is shaded by where it sits in its own column --
 * a ranking, useful for "who leads on what".
 *
 * With `expected`, it is shaded by the DISTANCE from what was expected, warm
 * above and cool below. That is the reading the expected-goals family exists
 * to support: nine goals on four expected is not form, it is a finishing run
 * that regresses; four on nine is a striker being failed by his luck, not by
 * his movement. The raw number cannot tell those apart and the gap always can.
 */
function heatmap(ctx: CanvasRenderingContext2D, spec: ChartSpec, plot: Plot, reveal: number) {
  const matrix = spec.matrix;
  if (!matrix || matrix.rows.length === 0 || matrix.columns.length === 0) return;

  const columns = matrix.columns.slice(0, 6);
  const rows = matrix.rows.slice(0, 6);
  const expected = matrix.expected;

  // Wide enough for a full name: "Ousmane Dembélé" was arriving as
  // "Ousmane Dem...", which is a poor way to label a comparison.
  const labelW = 232;
  const gridX = plot.x + labelW;
  const gridW = plot.w - labelW;
  const cellW = gridW / columns.length;
  const headerH = 40;
  const cellH = Math.min(58, (plot.h - headerH) / rows.length);

  // Column maxima, for the ranking colouring and for nothing else.
  const maxima = columns.map((_, c) =>
    Math.max(...rows.map((row) => Math.abs(row.values[c] ?? 0)), 1e-6),
  );

  ctx.fillStyle = PALETTE.ghost;
  ctx.font = `600 16px ${MONO}`;
  columns.forEach((name, c) => {
    const text = clip(ctx, name.toUpperCase(), cellW - 10);
    const w = ctx.measureText(text).width;
    ctx.fillText(text, gridX + c * cellW + (cellW - w) / 2, plot.y + 6);
  });

  if (expected) {
    ctx.fillStyle = PALETTE.ghost;
    ctx.font = `500 15px ${MONO}`;
    columns.forEach((_, c) => {
      const value = expected[c];
      if (value === undefined) return;
      const text = `att. ${format(value)}`;
      const w = ctx.measureText(text).width;
      ctx.fillText(text, gridX + c * cellW + (cellW - w) / 2, plot.y + 26);
    });
  }

  rows.forEach((row, r) => {
    const shown = Math.min(1, Math.max(0, reveal * rows.length - r));
    if (shown <= 0) return;
    ctx.globalAlpha = shown;
    const y = plot.y + headerH + r * cellH;

    ctx.fillStyle = row.mine ? PALETTE.lumen : PALETTE.ghost;
    ctx.font = `${row.mine ? 600 : 500} 20px ${SANS}`;
    ctx.fillText(clip(ctx, row.label, labelW - 18), plot.x, y + cellH / 2 + 7);

    columns.forEach((_, c) => {
      const value = row.values[c];
      const x = gridX + c * cellW;
      if (value === undefined) return;

      ctx.fillStyle = cellColour(value, expected?.[c], maxima[c]!);
      ctx.fillRect(x + 2, y + 2, cellW - 4, cellH - 4);

      if (row.mine) {
        ctx.strokeStyle = PALETTE.signal;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 2, y + 2, cellW - 4, cellH - 4);
      }

      ctx.fillStyle = PALETTE.lumen;
      ctx.font = `600 21px ${MONO}`;
      const text = format(value, spec.unit);
      const w = ctx.measureText(text).width;
      ctx.fillText(text, x + (cellW - w) / 2, y + cellH / 2 + 8);
    });
    ctx.globalAlpha = 1;
  });
}

/**
 * Warm when a figure beats what was expected of it, cool when it falls short,
 * and a plain ramp when there is nothing to expect it against.
 */
function cellColour(value: number, expected: number | undefined, max: number): string {
  if (expected === undefined || expected === 0) {
    const t = Math.min(1, Math.abs(value) / max);
    return `rgba(99,201,255,${0.08 + t * 0.42})`;
  }
  const gap = (value - expected) / Math.abs(expected);
  const t = Math.min(1, Math.abs(gap) / 0.6);
  return gap >= 0
    ? `rgba(79,224,196,${0.1 + t * 0.45})`
    : `rgba(255,122,47,${0.1 + t * 0.45})`;
}
