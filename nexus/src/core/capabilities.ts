import type { QualityTier } from './types';

export interface DeviceCapabilities {
  webgl: false | 1 | 2;
  gpu: string;
  vendor: string;
  cores: number;
  /** navigator.deviceMemory, in GB. 0 when unreported. */
  memory: number;
  maxTextureSize: number;
  /** Coarse pointer / no hover — phones and tablets. */
  touchPrimary: boolean;
  prefersReducedMotion: boolean;
  /** getUserMedia is reachable (requires a secure context). */
  cameraCapable: boolean;
  suggestedTier: QualityTier;
}

const FALLBACK: DeviceCapabilities = {
  webgl: false,
  gpu: 'unknown',
  vendor: 'unknown',
  cores: 4,
  memory: 0,
  maxTextureSize: 0,
  touchPrimary: false,
  prefersReducedMotion: false,
  cameraCapable: false,
  suggestedTier: 'low',
};

/** Shortened GPU string: "ANGLE (NVIDIA, GeForce RTX 4070 ...)" -> "GEFORCE RTX 4070". */
function tidyRenderer(raw: string): string {
  // Greedy on purpose: renderer strings nest parentheses ("Intel(R) UHD ..."),
  // and a lazy or negated-class match truncates at the first inner ")".
  const angle = raw.match(/ANGLE \((.*)\)\s*$/i);
  const body = angle?.[1] ?? raw;
  const parts = body.split(',').map((s) => s.trim());
  const best = parts.length > 1 ? parts[1] : parts[0];
  return (best ?? raw)
    .replace(/\((.*?)\)/g, '')
    .replace(/Direct3D.*$/i, '')
    .replace(/vs_\d+_\d+|ps_\d+_\d+/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 26)
    .toUpperCase();
}

let cached: DeviceCapabilities | null = null;

export function detectCapabilities(): DeviceCapabilities {
  if (cached) return cached;
  if (typeof window === 'undefined') return FALLBACK;

  const canvas = document.createElement('canvas');
  let gl: WebGL2RenderingContext | WebGLRenderingContext | null = null;
  let version: false | 1 | 2 = false;

  try {
    gl = canvas.getContext('webgl2') as WebGL2RenderingContext | null;
    if (gl) version = 2;
    else {
      gl = canvas.getContext('webgl') as WebGLRenderingContext | null;
      if (gl) version = 1;
    }
  } catch {
    gl = null;
  }

  let gpu = 'unknown';
  let vendor = 'unknown';
  let maxTextureSize = 0;

  if (gl) {
    maxTextureSize = gl.getParameter(gl.MAX_TEXTURE_SIZE) as number;
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    if (dbg) {
      gpu = tidyRenderer(String(gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)));
      vendor = String(gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL));
    } else {
      gpu = tidyRenderer(String(gl.getParameter(gl.RENDERER)));
      vendor = String(gl.getParameter(gl.VENDOR));
    }
    const lose = gl.getExtension('WEBGL_lose_context');
    lose?.loseContext();
  }

  const cores = navigator.hardwareConcurrency || 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 0;
  const touchPrimary = window.matchMedia('(pointer: coarse)').matches;
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const cameraCapable =
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    (window.isSecureContext || location.hostname === 'localhost');

  cached = {
    webgl: version,
    gpu,
    vendor,
    cores,
    memory,
    maxTextureSize,
    touchPrimary,
    prefersReducedMotion,
    cameraCapable,
    suggestedTier: suggestTier({ version, cores, memory, touchPrimary, gpu }),
  };
  return cached;
}

function suggestTier(o: {
  version: false | 1 | 2;
  cores: number;
  memory: number;
  touchPrimary: boolean;
  gpu: string;
}): QualityTier {
  if (!o.version) return 'low';
  if (o.version === 1) return 'low';
  if (o.touchPrimary) return o.cores >= 8 ? 'medium' : 'low';
  if (/SWIFTSHADER|LLVMPIPE|SOFTWARE|BASIC RENDER/i.test(o.gpu)) return 'low';
  const strong = /RTX|RADEON RX|ARC A|APPLE M[1-9]/i.test(o.gpu);
  if (strong && o.cores >= 8) return 'ultra';
  if (o.cores >= 8 && (o.memory === 0 || o.memory >= 8)) return 'high';
  if (o.cores >= 4) return 'medium';
  return 'low';
}
