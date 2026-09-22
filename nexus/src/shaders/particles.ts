import { CURL, NOISE } from './common';

/**
 * Volumetric mote field.
 *
 * All motion happens on the GPU: the CPU uploads a static cloud of seeds once
 * and never touches the buffer again. Position is a pure function of
 * (seed, time), so 6400 particles cost one draw call and zero JS per frame.
 */

export const PARTICLE_VERT = /* glsl */ `
uniform float uTime;
uniform float uSize;
uniform vec3 uBounds;
uniform float uDrift;
uniform float uFreeze;
uniform vec3 uAttractor;
uniform float uAttractStrength;

attribute vec3 aSeed;
attribute float aScale;
attribute float aPhase;

varying float vAlpha;
varying float vEnergy;

${NOISE}
${CURL}

void main() {
  // Freezing scales time, it does not stop it dead - a hard stop reads as a
  // dropped frame, a heavy slowdown reads as intent.
  float t = uTime * mix(1.0, 0.06, uFreeze);

  vec3 base = aSeed * uBounds;
  vec3 drift = curlDrift(base * 0.35 + aSeed * 3.1, t) * uDrift;

  // Slow vertical convection, wrapped so the volume never empties out.
  float rise = fract(aSeed.y * 0.5 + 0.5 + t * 0.012 * (0.4 + aScale)) - 0.5;
  vec3 pos = base + drift;
  pos.y = rise * uBounds.y * 2.0 + drift.y;

  // Motes are pulled gently toward the active hand, so the air acknowledges you.
  vec3 toHand = uAttractor - pos;
  float d = length(toHand);
  float pull = uAttractStrength / (1.0 + d * d * 1.6);
  pos += normalize(toHand + 1e-5) * pull;

  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  float dist = -mv.z;

  // Twinkle: two incommensurate rates so it never visibly loops.
  float tw = 0.55 + 0.45 * sin(t * (0.7 + aScale * 1.3) + aPhase * 6.28318);
  float tw2 = 0.7 + 0.3 * sin(t * 0.23 + aPhase * 12.0);

  vEnergy = tw * tw2 * (0.35 + pull * 9.0);
  // Fade in at the near plane and out into the fog.
  vAlpha = smoothstep(0.6, 3.0, dist) * (1.0 - smoothstep(18.0, 34.0, dist));

  gl_Position = projectionMatrix * mv;
  gl_PointSize = uSize * aScale * (300.0 / max(dist, 0.001));
}
`;

export const PARTICLE_FRAG = /* glsl */ `
uniform vec3 uColorCore;
uniform vec3 uColorEdge;
uniform float uOpacity;

varying float vAlpha;
varying float vEnergy;

void main() {
  vec2 uv = gl_PointCoord - 0.5;
  float r = dot(uv, uv) * 4.0;
  if (r > 1.0) discard;

  // Tight core, wide halo - reads as a lit mote rather than a soft blob.
  float core = pow(1.0 - r, 6.0);
  float halo = pow(1.0 - r, 1.6) * 0.35;

  vec3 color = mix(uColorEdge, uColorCore, core);
  float alpha = (core + halo) * vAlpha * uOpacity * vEnergy;
  if (alpha < 0.002) discard;

  gl_FragColor = vec4(color * (0.6 + vEnergy * 0.8), alpha);
}
`;
