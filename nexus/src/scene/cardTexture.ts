import { CanvasTexture, LinearFilter, SRGBColorSpace, type Texture } from 'three';
import { PALETTE } from '@/config/theme';
import type { ModuleDefinition } from '@/config/modules';
import { hash11 } from '@/core/math';
import { t, type Locale, type TranslationKey } from '@/i18n';
import { localizeModule, localizeValue, type ModuleText } from '@/i18n/modules';
import type { FaceState } from '@/modules/faces';

/**
 * Card faces are painted, not imported.
 *
 * Every glyph on a card is drawn to a 2D canvas at load time and uploaded as
 * a single texture. Three reasons this beats the alternatives:
 *
 *   - No font fetch, no FOUT, no CDN on the critical path.
 *   - The face participates in the glass refraction and the bloom pass, which
 *     a DOM overlay (drei's Html) fundamentally cannot.
 *   - One texture per card, one draw call, no SDF text atlas to manage.
 *
 * The cost is that faces are static. That is the right trade for phase 1:
 * live data arrives with the real modules, and at that point the painter takes
 * a values object instead of the definition.
 *
 * Textures are cached per (module, locale). Switching language repaints ten
 * canvases once and then hits cache forever — cheaper and simpler than trying
 * to overlay live DOM text onto a refracting glass slab.
 */

const W = 640;
const H = 888;
const PAD = 44;

const MONO = 'ui-monospace, "SF Mono", "JetBrains Mono", "Cascadia Mono", Menlo, monospace';
const SANS = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';

const cache = new Map<string, Texture>();
/** Live faces repaint whenever the numbers move, so the cache needs a ceiling. */
const CACHE_LIMIT = 48;

/** Identity of a painted face: same key, same pixels. */
function faceKey(face: FaceState | undefined): string {
  if (!face) return 'static';
  return (
    face.status +
    face.source +
    face.metrics.map((m) => `${m.label}${m.value}${m.level.toFixed(2)}`).join('|')
  );
}

export function getCardTexture(
  mod: ModuleDefinition,
  index: number,
  locale: Locale,
  face?: FaceState,
): Texture {
  const key = `${mod.id}:${index}:${locale}:${faceKey(face)}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const tex = paint(mod, index, localizeModule(mod, locale), face);
  cache.set(key, tex);

  // Evict oldest-first. Map preserves insertion order, and a card that is still
  // on screen will simply repaint on its next frame if it loses the race.
  while (cache.size > CACHE_LIMIT) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.get(oldest)?.dispose();
    cache.delete(oldest);
  }
  return tex;
}

export function disposeCardTextures(): void {
  cache.forEach((t) => t.dispose());
  cache.clear();
}

function paint(
  mod: ModuleDefinition,
  index: number,
  text: ModuleText,
  face?: FaceState,
): Texture {
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  const status = face?.status ?? mod.status;
  const accent = status === 'attention' ? PALETTE.ember : PALETTE.signal;

  drawGround(ctx);
  drawRegistration(ctx, accent);
  drawHeader(ctx, mod, index, accent, status);
  drawTitle(ctx, mod, text);
  drawSparkline(ctx, mod, accent);
  drawMetrics(ctx, mod, text, accent, face);
  drawFooter(ctx, mod, accent, face);

  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  texture.minFilter = LinearFilter;
  texture.magFilter = LinearFilter;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return texture;
}

// ---------------------------------------------------------------------------

function drawGround(ctx: CanvasRenderingContext2D) {
  const g = ctx.createLinearGradient(0, 0, W * 0.4, H);
  g.addColorStop(0, 'rgba(14, 26, 42, 0.92)');
  g.addColorStop(0.55, 'rgba(8, 15, 26, 0.88)');
  g.addColorStop(1, 'rgba(5, 9, 17, 0.94)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);

  // Micro dot grid — the Teenage Engineering tell. Kept far below text weight.
  ctx.fillStyle = 'rgba(99, 201, 255, 0.055)';
  for (let y = PAD; y < H - PAD; y += 16) {
    for (let x = PAD; x < W - PAD; x += 16) {
      ctx.fillRect(x, y, 1, 1);
    }
  }

  // Top light bleed, matching the overhead pool in the environment shader.
  const bleed = ctx.createLinearGradient(0, 0, 0, H * 0.42);
  bleed.addColorStop(0, 'rgba(99, 201, 255, 0.13)');
  bleed.addColorStop(1, 'rgba(99, 201, 255, 0)');
  ctx.fillStyle = bleed;
  ctx.fillRect(0, 0, W, H * 0.42);
}

function drawRegistration(ctx: CanvasRenderingContext2D, accent: string) {
  ctx.strokeStyle = hexA(accent, 0.5);
  ctx.lineWidth = 2;
  const s = 26;
  const corners: Array<[number, number, number, number]> = [
    [PAD, PAD, 1, 1],
    [W - PAD, PAD, -1, 1],
    [PAD, H - PAD, 1, -1],
    [W - PAD, H - PAD, -1, -1],
  ];
  for (const [x, y, dx, dy] of corners) {
    ctx.beginPath();
    ctx.moveTo(x, y + dy * s);
    ctx.lineTo(x, y);
    ctx.lineTo(x + dx * s, y);
    ctx.stroke();
  }
}

function drawHeader(
  ctx: CanvasRenderingContext2D,
  mod: ModuleDefinition,
  index: number,
  accent: string,
  status: ModuleDefinition['status'],
) {
  const y = PAD + 62;

  ctx.font = `600 20px ${MONO}`;
  ctx.fillStyle = hexA(PALETTE.ghost, 0.95);
  ctx.letterSpacing = '3px';
  ctx.fillText(String(index + 1).padStart(2, '0') + ' / 10', PAD + 6, y);

  // Status pip + label, right aligned.
  const label = t(`state.${status}` as TranslationKey);
  ctx.textAlign = 'right';
  ctx.font = `600 18px ${MONO}`;
  ctx.fillStyle = status === 'online' ? hexA(PALETTE.lock, 1) : hexA(PALETTE.ghost, 0.9);
  if (status === 'attention') ctx.fillStyle = hexA(PALETTE.ember, 1);
  ctx.fillText(label, W - PAD - 24, y);

  ctx.beginPath();
  ctx.arc(W - PAD - 8, y - 6, 5, 0, Math.PI * 2);
  ctx.fillStyle = status === 'standby' ? hexA(PALETTE.ghost, 0.6) : ctx.fillStyle;
  ctx.fill();
  ctx.textAlign = 'left';

  // Rule under the header.
  ctx.strokeStyle = hexA(accent, 0.22);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD + 6, y + 26);
  ctx.lineTo(W - PAD - 6, y + 26);
  ctx.stroke();
}

function drawTitle(ctx: CanvasRenderingContext2D, mod: ModuleDefinition, text: ModuleText) {
  ctx.letterSpacing = '0px';

  // The three-letter code, oversized. This is the card's identity at distance.
  ctx.font = `200 148px ${SANS}`;
  ctx.fillStyle = hexA(PALETTE.lumen, 0.96);
  ctx.fillText(mod.code, PAD + 2, PAD + 232);

  ctx.font = `500 40px ${SANS}`;
  ctx.letterSpacing = '-0.5px';
  ctx.fillStyle = hexA(PALETTE.lumen, 0.88);
  ctx.fillText(text.name, PAD + 6, PAD + 292);

  ctx.font = `400 19px ${MONO}`;
  ctx.letterSpacing = '0.5px';
  ctx.fillStyle = hexA(PALETTE.ghost, 1);
  wrap(ctx, text.descriptor.toUpperCase(), PAD + 6, PAD + 330, W - PAD * 2 - 12, 26);
  ctx.letterSpacing = '0px';
}

function drawSparkline(ctx: CanvasRenderingContext2D, mod: ModuleDefinition, accent: string) {
  const top = 430;
  const height = 96;
  const left = PAD + 6;
  const width = W - PAD * 2 - 12;
  const points = 52;

  ctx.strokeStyle = hexA(PALETTE.lumen, 0.06);
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = top + (height / 3) * i;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + width, y);
    ctx.stroke();
  }

  // Deterministic random walk — same card, same trace, every reload.
  const values: number[] = [];
  let v = 0.5;
  for (let i = 0; i < points; i++) {
    v += (hash11(mod.seed * 100 + i * 1.7) - 0.5) * 0.28;
    v = Math.max(0.06, Math.min(0.94, v));
    values.push(v);
  }

  ctx.beginPath();
  values.forEach((val, i) => {
    const x = left + (i / (points - 1)) * width;
    const y = top + height - val * height;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = hexA(accent, 0.85);
  ctx.lineWidth = 2;
  ctx.stroke();

  // Fill under the trace.
  ctx.lineTo(left + width, top + height);
  ctx.lineTo(left, top + height);
  ctx.closePath();
  const fill = ctx.createLinearGradient(0, top, 0, top + height);
  fill.addColorStop(0, hexA(accent, 0.22));
  fill.addColorStop(1, hexA(accent, 0));
  ctx.fillStyle = fill;
  ctx.fill();

  // Leading marker.
  const lastX = left + width;
  const lastY = top + height - values[values.length - 1]! * height;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
  ctx.fillStyle = hexA(PALETTE.lumen, 1);
  ctx.fill();
}

function drawMetrics(
  ctx: CanvasRenderingContext2D,
  mod: ModuleDefinition,
  text: ModuleText,
  accent: string,
  face?: FaceState,
) {
  // Live metrics replace the declared ones wholesale. Their labels are routed
  // through the same word catalogue the static values use, so a label that has
  // a translation gets one and the rest pass through untouched.
  const metrics = face?.metrics ?? mod.metrics;
  let y = 588;
  const left = PAD + 6;
  const right = W - PAD - 6;

  for (let m = 0; m < metrics.length; m++) {
    const metric = metrics[m]!;
    ctx.font = `500 18px ${MONO}`;
    ctx.letterSpacing = '2px';
    ctx.fillStyle = hexA(PALETTE.ghost, 1);
    ctx.fillText(face ? localizeValue(metric.label) : text.metrics[m] ?? metric.label, left, y);

    ctx.textAlign = 'right';
    ctx.font = `500 22px ${MONO}`;
    ctx.letterSpacing = '0px';
    ctx.fillStyle = hexA(PALETTE.lumen, 0.94);
    ctx.fillText(localizeValue(metric.value), right, y);
    ctx.textAlign = 'left';

    // Segmented bar — reads as an instrument, not a progress bar.
    const barY = y + 12;
    const segments = 28;
    const gap = 4;
    const segW = (right - left - gap * (segments - 1)) / segments;
    const lit = Math.round(metric.level * segments);
    for (let i = 0; i < segments; i++) {
      ctx.fillStyle = i < lit ? hexA(accent, 0.85) : hexA(PALETTE.lumen, 0.08);
      ctx.fillRect(left + i * (segW + gap), barY, segW, 3);
    }

    y += 62;
  }
  ctx.letterSpacing = '0px';
}

function drawFooter(
  ctx: CanvasRenderingContext2D,
  mod: ModuleDefinition,
  accent: string,
  face?: FaceState,
) {
  const y = H - PAD - 22;

  ctx.strokeStyle = hexA(accent, 0.2);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(PAD + 6, y - 30);
  ctx.lineTo(W - PAD - 6, y - 30);
  ctx.stroke();

  ctx.font = `500 17px ${MONO}`;
  ctx.letterSpacing = '2.5px';
  ctx.fillStyle = hexA(PALETTE.ghost, 0.95);
  ctx.fillText(t(`category.${mod.category}` as TranslationKey), PAD + 6, y);

  ctx.textAlign = 'right';
  ctx.fillStyle = hexA(accent, 0.8);
  ctx.fillText(`NX.${mod.code}`, W - PAD - 6, y);
  ctx.textAlign = 'left';

  // Provenance, small and quiet. A number with no stated origin is a number
  // you cannot check.
  if (face?.source) {
    ctx.font = `500 14px ${MONO}`;
    ctx.letterSpacing = '1.5px';
    ctx.fillStyle = hexA(PALETTE.ghost, 0.65);
    ctx.fillText(face.source.toUpperCase().slice(0, 34), PAD + 6, y - 44);
  }
  ctx.letterSpacing = '0px';
}

// ---------------------------------------------------------------------------

/** #rrggbb + alpha -> rgba() string. */
function hexA(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function wrap(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
): void {
  const words = text.split(' ');
  let line = '';
  let cursor = y;
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) {
      ctx.fillText(line, x, cursor);
      line = word;
      cursor += lineHeight;
    } else {
      line = test;
    }
  }
  if (line) ctx.fillText(line, x, cursor);
}
