/**
 * Where the MediaPipe runtime comes from.
 *
 * Preference order is local -> CDN. `npm run setup:assets` copies the WASM
 * bundle out of node_modules and downloads the landmark model into /public,
 * which makes the app fully offline-capable and removes a third-party runtime
 * dependency from the critical path. If those files are absent (fresh clone,
 * no network at install time) we transparently fall back to the CDN.
 */

const VERSION = '0.10.21';

export const LOCAL_WASM = '/mediapipe/wasm';
export const CDN_WASM = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VERSION}/wasm`;

export const LOCAL_MODEL = '/models/hand_landmarker.task';
export const CDN_MODEL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task';

const envWasm = process.env.NEXT_PUBLIC_MEDIAPIPE_WASM;
const envModel = process.env.NEXT_PUBLIC_HAND_MODEL;

async function exists(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'HEAD', cache: 'force-cache' });
    return res.ok;
  } catch {
    return false;
  }
}

export interface ResolvedAssets {
  wasm: string;
  model: string;
  /** True when everything was served from our own origin. */
  local: boolean;
}

let cached: Promise<ResolvedAssets> | null = null;

export function resolveAssets(): Promise<ResolvedAssets> {
  cached ??= (async () => {
    if (envWasm && envModel) return { wasm: envWasm, model: envModel, local: false };
    const [hasWasm, hasModel] = await Promise.all([
      exists(`${LOCAL_WASM}/vision_wasm_internal.wasm`),
      exists(LOCAL_MODEL),
    ]);
    return {
      wasm: envWasm ?? (hasWasm ? LOCAL_WASM : CDN_WASM),
      model: envModel ?? (hasModel ? LOCAL_MODEL : CDN_MODEL),
      local: hasWasm && hasModel,
    };
  })();
  return cached;
}
