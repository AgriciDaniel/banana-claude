/**
 * Vendors the MediaPipe runtime into /public.
 *
 * Two things happen here, both optional and both non-fatal:
 *
 *   1. The WASM bundle is copied out of node_modules. It already exists on
 *      disk after `npm install`, so this never touches the network.
 *   2. The hand landmark model (~7 MB) is downloaded once and cached.
 *
 * If either step fails — offline install, restricted network, corporate proxy
 * — the app falls back to the CDN at runtime (see src/gesture/assets.ts). This
 * script makes NEXUS work offline; it is not required for it to work at all.
 */

import { cp, mkdir, stat, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WASM_SRC = join(root, 'node_modules', '@mediapipe', 'tasks-vision', 'wasm');
const WASM_DEST = join(root, 'public', 'mediapipe', 'wasm');
const MODEL_DEST = join(root, 'public', 'models', 'hand_landmarker.task');
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';

const ok = (m) => console.log(`  \u2713 ${m}`);
const warn = (m) => console.warn(`  ! ${m}`);

async function copyWasm() {
  if (!existsSync(WASM_SRC)) {
    warn('MediaPipe WASM not found in node_modules — will use the CDN at runtime.');
    return false;
  }
  await mkdir(WASM_DEST, { recursive: true });
  await cp(WASM_SRC, WASM_DEST, { recursive: true });
  ok(`WASM runtime vendored to public/mediapipe/wasm`);
  return true;
}

async function fetchModel() {
  if (existsSync(MODEL_DEST)) {
    const info = await stat(MODEL_DEST);
    if (info.size > 1_000_000) {
      ok(`Model already present (${(info.size / 1e6).toFixed(1)} MB)`);
      return true;
    }
  }
  await mkdir(dirname(MODEL_DEST), { recursive: true });
  try {
    const res = await fetch(MODEL_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = Buffer.from(await res.arrayBuffer());
    await writeFile(MODEL_DEST, buffer);
    ok(`Hand landmark model downloaded (${(buffer.length / 1e6).toFixed(1)} MB)`);
    return true;
  } catch (err) {
    warn(`Model download failed (${err.message}) — will use the CDN at runtime.`);
    return false;
  }
}

console.log('NEXUS · vendoring tracking assets');
const [wasm, model] = await Promise.all([copyWasm(), fetchModel()]);
console.log(
  wasm && model
    ? 'NEXUS · offline-capable: tracking assets served from this origin.\n'
    : 'NEXUS · partial: missing assets will be fetched from the CDN.\n',
);
