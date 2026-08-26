import { Color, MeshStandardMaterial } from 'three';
import { PALETTE } from '@/config/theme';

/**
 * The shell.
 *
 * The figure was a hologram: additive, transparent, lit by nothing, read
 * entirely off its own rim. A plated machine is the opposite proposition. It is
 * opaque, it is white, and it is only legible because light falls on it -- so
 * it has to be a real lit material, taking the room's key light and the
 * environment the ring is already reflecting.
 *
 * That rules out a hand-written shader. Re-deriving physically based shading
 * to add two glowing lines to it would be a great deal of work to arrive back
 * where three already is, so this patches the standard material instead:
 * everything about the lighting stays stock, and the seams are injected into
 * the one place the emissive term is assembled.
 */

export interface PlateOptions {
  /** Plate divisions along the part. 0 leaves the shell unbroken. */
  plates: number;
  /** Base shell colour. */
  colour?: string;
  metalness?: number;
  roughness?: number;
  /** Seams glow this colour. */
  seam?: string;
}

/*
 * The recess a seam sits in. Not black -- a seam reads as a channel cut into
 * the shell, and a channel still catches a little light. Pure black reads as a
 * hole and makes the plates look like separate floating pieces.
 */
const RECESS = 'vec3(0.055, 0.062, 0.075)';

/*
 * Low metalness, and that is not a stylistic preference.
 *
 * A metal surface is almost entirely reflection, so a metal in an unlit room
 * is black -- the first shell came out at 0.55 and read as gunmetal grey in a
 * scene whose only strong light is blue. The references are glossy white
 * ceramic: bright diffuse, tight highlight, barely any metal at all.
 */
export function makePlate({
  plates,
  colour = '#F4F8FC',
  metalness = 0.14,
  roughness = 0.28,
  seam = PALETTE.signal,
}: PlateOptions): MeshStandardMaterial {
  const material = new MeshStandardMaterial({
    color: new Color(colour),
    metalness,
    roughness,
    emissive: new Color('#000000'),
    transparent: true,
    opacity: 1,
  });

  /*
   * `vUv` only exists in the compiled shader if something asked for it, and
   * nothing here uses a texture. Declaring USE_UV is what makes the seams
   * possible at all.
   */
  material.defines = { ...(material.defines ?? {}), USE_UV: '' };

  material.onBeforeCompile = (shader) => {
    shader.uniforms.uSeamColour = { value: new Color(seam) };
    shader.uniforms.uPlates = { value: plates };
    shader.uniforms.uGlow = { value: 1 };
    /* Kept so the frame loop can reach the glow without re-finding it. */
    material.userData.shader = shader;

    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
        uniform vec3 uSeamColour;
        uniform float uPlates;
        uniform float uGlow;`,
      )
      .replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>

        /*
         * Panel lines, from the geometry's own UVs: v runs along the part, u
         * around it. Bands across, and one seam down each side where the
         * revolution closes -- which is where a real shell would be split to
         * get it onto the frame in the first place.
         */
        float band = fract(vUv.y * uPlates);
        float across = smoothstep(0.05, 0.0, min(band, 1.0 - band));
        float around = abs(fract(vUv.x * 2.0 + 0.25) - 0.5) * 2.0;
        float along = smoothstep(0.982, 1.0, around);
        float seam = max(across, along) * step(0.5, uPlates);

        // The channel first, then the light sitting in it.
        diffuseColor.rgb = mix(diffuseColor.rgb, ${RECESS}, seam * 0.9);
        totalEmissiveRadiance += uSeamColour * seam * uGlow;`,
      );
  };

  /*
   * Two shells with different plate counts must not share a compiled program,
   * and three's cache key does not know about anything injected by hand.
   */
  material.customProgramCacheKey = () => `figure-plate-${plates}-${seam}`;

  return material;
}

/** Set the seam brightness on a material built above. */
export function setGlow(material: MeshStandardMaterial, glow: number): void {
  const shader = material.userData.shader as
    | { uniforms: { uGlow?: { value: number } } }
    | undefined;
  if (shader?.uniforms.uGlow) shader.uniforms.uGlow.value = glow;
}
