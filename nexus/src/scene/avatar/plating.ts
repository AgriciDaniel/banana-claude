import { Color, MeshStandardMaterial, type Texture } from 'three';
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

/**
 * The face.
 *
 * The body is lathed -- profiles revolved around an axis -- and a lathe is
 * rotationally symmetric by construction. It can give a skull; it can never
 * give a brow, a nose or a mouth. So the face is a generated image, and this is
 * the material that makes it belong to the body rather than sit on top of it.
 *
 * Lit, not added. The earlier holographic face was drawn additively, which was
 * right on a translucent figure and wrong the moment the shell became opaque
 * ceramic: an additive face floats in front of a solid head instead of being
 * part of it. Here it goes through the same standard shading as every plate, so
 * the room's key light falls across it and it turns with the head correctly.
 *
 * Three things are injected:
 *
 *   - The mouth opens. The rows around the lips are stretched downward on the
 *     speech envelope, and a dark gap is painted into the parting. This is the
 *     only way a still image can speak, and it is why the prompt insists the
 *     generated mouth arrives closed.
 *   - The frame's corners are masked away with an ellipse. A rectangle cannot
 *     end abruptly on a face.
 *   - Only the coloured lights glow. Feeding the whole image to an emissive map
 *     would light the white shell as brightly as the optics; keying the
 *     emissive on SATURATION picks out exactly the amber eyes, the cyan seams
 *     and the violet brow bar, and leaves the ceramic to the key light.
 */
export function makeFace(map: Texture): MeshStandardMaterial {
  const material = new MeshStandardMaterial({
    color: new Color('#FFFFFF'),
    roughness: 0.3,
    metalness: 0.05,
    transparent: true,
  });
  material.defines = { ...(material.defines ?? {}), USE_UV: '' };

  material.onBeforeCompile = (shader) => {
    shader.uniforms.uFace = { value: map };
    shader.uniforms.uJaw = { value: 0 };
    shader.uniforms.uAlpha = { value: 1 };
    shader.uniforms.uCrop = { value: 1 };
    material.userData.shader = shader;

    shader.fragmentShader = shader.fragmentShader
      .replace(
        '#include <common>',
        `#include <common>
        uniform sampler2D uFace;
        uniform float uJaw;
        uniform float uAlpha;
        uniform float uCrop;
        vec4 faceSample;`,
      )
      .replace(
        '#include <map_fragment>',
        `#include <map_fragment>

        /*
         * Mirrored in x: the figure faces +Z and is seen from +Z, which
         * reverses left and right. Cropped to the centre square, so a frame
         * that comes back landscape loses its sides rather than stretching.
         */
        vec2 faceUv = vec2(0.5 - (vUv.x - 0.5) * uCrop, vUv.y);

        /*
         * Open the mouth. Sampling from further UP the image drags the content
         * DOWN, so the lips and the chin below them stretch apart. Bounded to a
         * disc around the mouth, or the whole lower face would slide.
         */
        float atMouth = 1.0 - smoothstep(0.0, 0.135, distance(vUv, vec2(0.5, 0.235)));
        faceUv.y += atMouth * uJaw * 0.052;

        faceSample = texture2D(uFace, faceUv);
        diffuseColor.rgb *= faceSample.rgb;

        // The parting itself: dark, and only as wide as the mouth.
        float gap = (1.0 - smoothstep(0.0, 0.05, abs(vUv.y - 0.222)))
                  * (1.0 - smoothstep(0.055, 0.1, abs(vUv.x - 0.5)));
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.015, 0.012, 0.01), gap * uJaw * 0.92);

        // The frame's corners, taken out with an ellipse.
        vec2 edge = (vUv - 0.5) * vec2(2.06, 1.94);
        diffuseColor.a *= (1.0 - smoothstep(0.74, 1.0, length(edge))) * uAlpha;`,
      )
      .replace(
        '#include <emissivemap_fragment>',
        `#include <emissivemap_fragment>

        float hi = max(max(faceSample.r, faceSample.g), faceSample.b);
        float lo = min(min(faceSample.r, faceSample.g), faceSample.b);
        float sat = hi > 0.001 ? (hi - lo) / hi : 0.0;
        totalEmissiveRadiance += faceSample.rgb * smoothstep(0.22, 0.55, sat) * 2.6;`,
      );
  };

  material.customProgramCacheKey = () => 'figure-face';
  return material;
}

/** Drive the face: how far the mouth is open, and how present the body is. */
export function setFace(material: MeshStandardMaterial, jaw: number, alpha: number): void {
  const shader = material.userData.shader as
    | { uniforms: { uJaw?: { value: number }; uAlpha?: { value: number } } }
    | undefined;
  if (!shader) return;
  if (shader.uniforms.uJaw) shader.uniforms.uJaw.value = jaw;
  if (shader.uniforms.uAlpha) shader.uniforms.uAlpha.value = alpha;
}

/**
 * Tell the face how much of its frame to use.
 *
 * Read off the loaded image rather than assumed: the model answers square when
 * asked to and landscape when it feels like it, and a face stretched across a
 * square plane is the loudest possible way to discover which happened.
 */
export function setFaceCrop(material: MeshStandardMaterial, aspect: number): void {
  const shader = material.userData.shader as
    | { uniforms: { uCrop?: { value: number } } }
    | undefined;
  if (shader?.uniforms.uCrop) shader.uniforms.uCrop.value = aspect > 1 ? 1 / aspect : 1;
}
