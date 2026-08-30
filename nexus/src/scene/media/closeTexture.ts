import { CanvasTexture, SRGBColorSpace, type Texture } from 'three';
import { PALETTE } from '@/config/theme';

/**
 * The little cross that dismisses a frame.
 *
 * Painted once and shared by every frame: it is the same eight pixels of
 * geometry each time, and a texture per panel would be waste for a mark this
 * small. Drawn rather than typed so it needs no font to have loaded.
 */

let cached: Texture | null = null;
const SIZE = 128;

export function getCloseTexture(): Texture {
  if (cached) return cached;

  const canvas = document.createElement('canvas');
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext('2d')!;

  const centre = SIZE / 2;
  ctx.beginPath();
  ctx.arc(centre, centre, centre - 6, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(6,11,20,0.82)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(99,201,255,0.55)';
  ctx.lineWidth = 4;
  ctx.stroke();

  const arm = SIZE * 0.19;
  ctx.strokeStyle = PALETTE.lumen;
  ctx.lineWidth = 9;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(centre - arm, centre - arm);
  ctx.lineTo(centre + arm, centre + arm);
  ctx.moveTo(centre + arm, centre - arm);
  ctx.lineTo(centre - arm, centre + arm);
  ctx.stroke();

  cached = new CanvasTexture(canvas);
  cached.colorSpace = SRGBColorSpace;
  cached.anisotropy = 4;
  return cached;
}
