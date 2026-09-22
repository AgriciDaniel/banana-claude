import { NOISE } from './common';

/**
 * Volumetric light beam.
 *
 * A cone rendered additively with a soft radial falloff and a slow noise scan
 * running along its length. Cheaper than raymarched god rays by two orders of
 * magnitude, and at this fog density visually indistinguishable.
 */

export const BEAM_VERT = /* glsl */ `
varying vec2 vUv;
varying vec3 vPos;
varying vec3 vNormal;
varying vec3 vViewDir;

void main() {
  vUv = uv;
  vPos = position;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vViewDir = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

export const BEAM_FRAG = /* glsl */ `
uniform float uTime;
uniform vec3 uColor;
uniform float uIntensity;
uniform float uSeed;
uniform float uFreeze;

varying vec2 vUv;
varying vec3 vPos;
varying vec3 vNormal;
varying vec3 vViewDir;

${NOISE}

void main() {
  float t = uTime * mix(1.0, 0.08, uFreeze);

  // Fade at both ends so the cone has no visible geometry termination.
  float lengthFade = smoothstep(0.0, 0.22, vUv.y) * (1.0 - smoothstep(0.55, 1.0, vUv.y));

  // Grazing angles are brighter: the classic volumetric silhouette cue.
  float facing = 1.0 - abs(dot(normalize(vNormal), vViewDir));
  float rim = pow(facing, 1.8);

  // Dust scanning down the shaft.
  float scan = fbm(vec3(vUv.x * 3.0, vUv.y * 2.2 - t * 0.09, uSeed * 17.0));
  float flicker = 0.82 + 0.18 * sin(t * 0.6 + uSeed * 9.0);

  float alpha = lengthFade * rim * (0.35 + scan * 0.75) * uIntensity * flicker;
  alpha *= 0.16;
  if (alpha < 0.001) discard;

  gl_FragColor = vec4(uColor * (0.8 + scan * 0.6), alpha);
}
`;
