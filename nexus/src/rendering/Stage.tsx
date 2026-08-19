'use client';

import { Canvas } from '@react-three/fiber';
import { ACESFilmicToneMapping, SRGBColorSpace } from 'three';
import { SPACE, PALETTE } from '@/config/theme';
import { useSystemStore } from '@/stores/useSystemStore';
import { SceneGraph } from '@/scene/SceneGraph';
import { log } from '@/stores/useLogStore';
import { t } from '@/i18n';

/**
 * The renderer.
 *
 * Antialiasing is off at the context level on purpose — MSAA on the main
 * framebuffer is wasted when the image is going through a post pipeline, so
 * SMAA/MSAA is applied inside the composer where it can be tier-gated instead.
 */
export function Stage() {
  const profile = useSystemStore((s) => s.profile);

  return (
    <Canvas
      dpr={[1, profile.dpr]}
      frameloop="always"
      shadows={false}
      camera={{ position: SPACE.cameraStart, fov: 42, near: 0.1, far: 140 }}
      gl={{
        antialias: false,
        alpha: false,
        stencil: false,
        depth: true,
        powerPreference: 'high-performance',
        preserveDrawingBuffer: false,
        failIfMajorPerformanceCaveat: false,
      }}
      onCreated={({ gl, scene }) => {
        gl.setClearColor(PALETTE.void, 1);
        gl.toneMapping = ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
        gl.outputColorSpace = SRGBColorSpace;
        /*
         * Refraction re-renders the scene into an offscreen buffer. At full
         * resolution that doubles the cost of the frame for an effect that is
         * being viewed THROUGH frosted glass — half resolution is free quality.
         */
        gl.transmissionResolutionScale = 0.5;
        scene.matrixWorldAutoUpdate = true;
        log.sys(t('log.renderer', { api: gl.capabilities.isWebGL2 ? 'WEBGL2' : 'WEBGL1' }));
      }}
      className="fixed inset-0"
    >
      <SceneGraph />
    </Canvas>
  );
}
