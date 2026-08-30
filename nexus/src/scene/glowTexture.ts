import { CanvasTexture, LinearFilter, SRGBColorSpace, type Texture } from 'three';

/** Radial falloff sprite, generated once and shared by every glow plane. */
let glow: Texture | null = null;

export function getGlowTexture(): Texture {
  if (glow) return glow;
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;

  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  // A tight core with a long tail reads as light; a linear ramp reads as paint.
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.18, 'rgba(255,255,255,0.55)');
  g.addColorStop(0.45, 'rgba(255,255,255,0.16)');
  g.addColorStop(0.75, 'rgba(255,255,255,0.035)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);

  glow = new CanvasTexture(canvas);
  glow.colorSpace = SRGBColorSpace;
  glow.minFilter = LinearFilter;
  glow.magFilter = LinearFilter;
  return glow;
}
