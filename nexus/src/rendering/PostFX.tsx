'use client';

import { useMemo } from 'react';
import { Bloom, ChromaticAberration, DepthOfField, EffectComposer, Noise, Vignette } from '@react-three/postprocessing';
import { BlendFunction, KernelSize } from 'postprocessing';
import { Vector2 } from 'three';
import { useSystemStore } from '@/stores/useSystemStore';

/**
 * Post pipeline.
 *
 * Order matters and is not arbitrary: depth of field runs before bloom so
 * out-of-focus highlights bloom as the soft discs they have become, not as the
 * sharp points they used to be. Chromatic aberration and grain come last, on
 * the finished image, because they are lens artefacts rather than scene light.
 *
 * Every stage is gated by the quality profile, so the composer rebuilds only
 * when the governor actually changes tier.
 */
export function PostFX() {
  const profile = useSystemStore((s) => s.profile);
  const reduced = useSystemStore((s) => s.capabilities?.prefersReducedMotion ?? false);

  const aberration = useMemo(() => new Vector2(0.00032, 0.00024), []);

  if (!profile.bloom && !profile.chromaticAberration) return null;

  return (
    <EffectComposer
      multisampling={profile.tier === 'ultra' ? 4 : 0}
      enableNormalPass={false}
      key={profile.tier}
    >
      {profile.depthOfField ? (
        <DepthOfField
          /*
           * World units, not the normalised 0..1 focusDistance. The camera sits
           * ~5.7m from the front card, so that is the focal plane; everything
           * from the ring inward stays sharp and only the fog softens. Using
           * the normalised form put the focal plane at the near clip and blurred
           * the entire scene, including the HUD-adjacent text.
           */
          worldFocusDistance={5.7}
          worldFocusRange={5.5}
          focalLength={0.02}
          bokehScale={2.4}
          height={480}
        />
      ) : (
        <></>
      )}

      {profile.bloom ? (
        <Bloom
          intensity={0.82}
          /*
           * Threshold is high on purpose. Card faces are near-white type on a
           * dark plate; a low threshold blooms the GLYPHS, which looks like a
           * lens flare and reads as illegible. Only emissive edges, the frame
           * pulse and the motes should be above this line.
           */
          luminanceThreshold={0.52}
          luminanceSmoothing={0.28}
          mipmapBlur
          levels={profile.bloomLevels}
          kernelSize={KernelSize.LARGE}
        />
      ) : (
        <></>
      )}

      {profile.chromaticAberration && !reduced ? (
        <ChromaticAberration offset={aberration} />
      ) : (
        <></>
      )}

      <Vignette offset={0.24} darkness={0.82} blendFunction={BlendFunction.NORMAL} />

      {profile.filmGrain ? (
        <Noise opacity={0.035} blendFunction={BlendFunction.OVERLAY} premultiply />
      ) : (
        <></>
      )}
    </EffectComposer>
  );
}
