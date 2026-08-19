import { FilesetResolver, HandLandmarker, type HandLandmarkerResult } from '@mediapipe/tasks-vision';
import { resolveAssets } from './assets';

/**
 * Camera + MediaPipe lifecycle.
 *
 * Owns exactly two resources - a MediaStream and a HandLandmarker - and
 * guarantees both are released on dispose. Init is idempotent and abortable so
 * React StrictMode's double-mount cannot leave a camera light on or leak a
 * second WASM instance.
 */

export type TrackerPhase = 'idle' | 'loading' | 'ready' | 'denied' | 'error';

export interface TrackerOptions {
  numHands?: number;
  minDetectionConfidence?: number;
  minPresenceConfidence?: number;
  minTrackingConfidence?: number;
  width?: number;
  height?: number;
}

const DEFAULTS: Required<TrackerOptions> = {
  numHands: 2,
  minDetectionConfidence: 0.55,
  minPresenceConfidence: 0.55,
  minTrackingConfidence: 0.5,
  width: 640,
  height: 480,
};

export class HandTracker {
  readonly video: HTMLVideoElement;
  phase: TrackerPhase = 'idle';
  error: string | null = null;
  /** True when the WASM backend accepted the GPU delegate. */
  gpuDelegate = false;

  private landmarker: HandLandmarker | null = null;
  private stream: MediaStream | null = null;
  private disposed = false;
  private lastTimestamp = -1;
  private lastVideoTime = -1;
  private opts: Required<TrackerOptions>;

  constructor(options: TrackerOptions = {}) {
    this.opts = { ...DEFAULTS, ...options };
    this.video = document.createElement('video');
    this.video.playsInline = true;
    this.video.muted = true;
    this.video.autoplay = true;
    this.video.width = this.opts.width;
    this.video.height = this.opts.height;
  }

  async init(): Promise<void> {
    if (this.phase !== 'idle') return;
    this.phase = 'loading';

    try {
      await this.openCamera();
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      this.phase = name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'error';
      this.error = describe(err);
      throw err;
    }

    if (this.disposed) return;

    try {
      const assets = await resolveAssets();
      const fileset = await FilesetResolver.forVisionTasks(assets.wasm);
      if (this.disposed) return;

      this.landmarker = await this.createLandmarker(fileset, assets.model);
      if (this.disposed) {
        this.landmarker.close();
        this.landmarker = null;
        return;
      }
      this.phase = 'ready';
    } catch (err) {
      this.phase = 'error';
      this.error = describe(err);
      throw err;
    }
  }

  private async createLandmarker(
    fileset: Awaited<ReturnType<typeof FilesetResolver.forVisionTasks>>,
    model: string,
  ): Promise<HandLandmarker> {
    const base = {
      runningMode: 'VIDEO' as const,
      numHands: this.opts.numHands,
      minHandDetectionConfidence: this.opts.minDetectionConfidence,
      minHandPresenceConfidence: this.opts.minPresenceConfidence,
      minTrackingConfidence: this.opts.minTrackingConfidence,
    };
    try {
      const gpu = await HandLandmarker.createFromOptions(fileset, {
        ...base,
        baseOptions: { modelAssetPath: model, delegate: 'GPU' },
      });
      this.gpuDelegate = true;
      return gpu;
    } catch {
      // Software fallback: slower, but keeps tracking alive on locked-down GPUs.
      this.gpuDelegate = false;
      return HandLandmarker.createFromOptions(fileset, {
        ...base,
        baseOptions: { modelAssetPath: model, delegate: 'CPU' },
      });
    }
  }

  private async openCamera(): Promise<void> {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      throw new Error('getUserMedia unavailable in this context');
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: this.opts.width },
        height: { ideal: this.opts.height },
        frameRate: { ideal: 30, max: 60 },
        facingMode: 'user',
      },
      audio: false,
    });

    if (this.disposed) {
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    this.stream = stream;
    this.video.srcObject = stream;
    await new Promise<void>((resolve, reject) => {
      const onReady = () => {
        this.video.removeEventListener('loadeddata', onReady);
        this.video.play().then(resolve).catch(reject);
      };
      this.video.addEventListener('loadeddata', onReady);
      if (this.video.readyState >= 2) onReady();
    });
  }

  /**
   * Run inference for the current video frame.
   * Returns null when the frame is not new - MediaPipe rejects repeated
   * timestamps, and re-running on a stale frame is wasted GPU time.
   */
  detect(nowMs: number): HandLandmarkerResult | null {
    if (!this.landmarker || this.phase !== 'ready') return null;
    if (this.video.readyState < 2) return null;
    if (this.video.currentTime === this.lastVideoTime) return null;
    this.lastVideoTime = this.video.currentTime;
    const ts = Math.max(nowMs, this.lastTimestamp + 1);
    this.lastTimestamp = ts;
    try {
      return this.landmarker.detectForVideo(this.video, ts);
    } catch {
      return null;
    }
  }

  get resolution(): { width: number; height: number } {
    return {
      width: this.video.videoWidth || this.opts.width,
      height: this.video.videoHeight || this.opts.height,
    };
  }

  dispose(): void {
    this.disposed = true;
    this.phase = 'idle';
    this.landmarker?.close();
    this.landmarker = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.video.pause();
  }
}

function describe(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === 'NotAllowedError') return 'Camera permission denied';
    if (err.name === 'NotFoundError') return 'No camera device found';
    if (err.name === 'NotReadableError') return 'Camera in use by another app';
    return err.message;
  }
  return String(err);
}
