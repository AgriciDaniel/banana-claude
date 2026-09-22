import { NOISE } from './common';

/**
 * Particle text.
 *
 * The assistant's words are rasterised to an offscreen canvas, the lit pixels
 * become target positions, and a fixed pool of particles flies onto them. Each
 * particle carries its own spawn time, so glyphs assemble in reading order as
 * the model streams rather than the whole paragraph snapping into place.
 *
 * All the motion is in the vertex shader. The CPU only ever uploads new target
 * positions - at about 8 Hz, not per frame - so a 6000-particle sentence costs
 * one draw call and no per-frame JavaScript.
 */

export const HOLO_TEXT_VERT = /* glsl */ `
uniform float uTime;
/** Diameter of one particle in WORLD units. */
uniform float uWorldSize;
/**
 * viewportHeightPx / (2 * tan(fov/2)). Multiplying a world size by this and
 * dividing by view distance gives the correct size in pixels. The previous
 * version used a hardcoded 260.0, which produced 84-pixel particles: fifteen
 * hundred of them overlapped into a solid white slab.
 */
uniform float uPixelScale;
uniform float uDissolve;
uniform float uLevel;
uniform float uFreeze;

attribute vec3 aTarget;
attribute vec3 aSeed;
attribute float aSpawn;
attribute float aActive;

varying float vAlpha;
varying float vHeat;

${NOISE}

void main() {
  float t = uTime;

  // --- assembly ---------------------------------------------------------
  // Age since this particle was assigned a glyph. Negative means it has not
  // been assigned yet and must stay invisible.
  float age = t - aSpawn;
  float appear = clamp(age / 0.62, 0.0, 1.0);
  // Ease out back: a slight overshoot as each particle lands on its glyph.
  float e = 1.0 - pow(1.0 - appear, 3.0);
  float overshoot = sin(appear * 3.14159) * 0.06 * (1.0 - appear);

  // Where the particle comes FROM: a loose cloud around its destination,
  // biased outward and downward so text seems to condense out of the air.
  vec3 scatter = aTarget + vec3(
    (aSeed.x - 0.5) * 2.4,
    (aSeed.y - 0.5) * 1.1 - 0.35,
    (aSeed.z - 0.5) * 1.6
  );

  vec3 pos = mix(scatter, aTarget, e);

  // --- settled drift -----------------------------------------------------
  // Assembled text is never perfectly still; it shimmers very slightly.
  float drift = 0.006 * (1.0 - uFreeze);
  pos.x += vnoise(vec3(aSeed.xy * 8.0, t * 0.35)) * drift;
  pos.y += vnoise(vec3(aSeed.yz * 8.0, t * 0.31 + 4.0)) * drift;
  pos.z += vnoise(vec3(aSeed.zx * 8.0, t * 0.27 + 8.0)) * drift * 2.0;

  // Speech makes the glyphs breathe outward from the baseline.
  pos.z += uLevel * 0.05 * (aSeed.z - 0.5);
  pos += normalize(aTarget - vec3(0.0, aTarget.y, 0.0) + 1e-5) * overshoot;

  // --- dissolve ---------------------------------------------------------
  // Old turns blow away rather than fading: motion reads as "replaced",
  // opacity alone reads as "broken".
  if (uDissolve > 0.0) {
    vec3 away = vec3(
      (aSeed.x - 0.5) * 3.0,
      0.8 + aSeed.y * 1.2,
      (aSeed.z - 0.5) * 2.0
    );
    pos += away * uDissolve * uDissolve;
  }

  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  float dist = -mv.z;

  vHeat = (1.0 - e) * 0.85 + uLevel * 0.35;
  vAlpha = aActive * appear * (1.0 - uDissolve);

  gl_Position = projectionMatrix * mv;
  // Slightly larger while in flight, so incoming particles read as motion.
  gl_PointSize = uWorldSize * uPixelScale / max(dist, 0.001) * (1.0 + (1.0 - e) * 0.7);
}
`;

export const HOLO_TEXT_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform vec3 uHot;
uniform float uOpacity;

varying float vAlpha;
varying float vHeat;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float r = dot(uv, uv) * 4.0;
  if (r > 1.0) discard;

  float core = pow(1.0 - r, 2.0);
  float halo = pow(1.0 - r, 1.0) * 0.22;

  // In-flight particles run hot and white; settled glyphs cool to the
  // interface blue, so you can see the sentence finish assembling.
  vec3 color = mix(uColor, uHot, clamp(vHeat, 0.0, 1.0));

  float alpha = (core + halo) * vAlpha * uOpacity;
  if (alpha < 0.003) discard;

  // Pushed above 1.0 on purpose: these are emissive glyphs floating in a dark
  // volume, and the bloom pass wants something to catch. Rendered additively,
  // so the overlap between neighbouring particles is what forms the stroke.
  gl_FragColor = vec4(color * (1.15 + vHeat * 0.8), alpha);
}
`;
