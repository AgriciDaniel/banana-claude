import { NOISE } from './common';

/**
 * The assistant's body.
 *
 * A displaced sphere at the centre of the ring. It is the point the voice is
 * spatialised from, so it has to look like the thing that is speaking: the
 * surface is driven by the live speech envelope, which means the shape you see
 * and the sound you hear are the same signal.
 */

export const PRESENCE_VERT = /* glsl */ `
uniform float uTime;
uniform float uLevel;
uniform float uAwake;

varying vec3 vNormal;
varying vec3 vView;
varying float vDisplace;

${NOISE}

void main() {
  vec3 n = normalize(position);

  // Two noise fields at different scales and speeds: a slow swell that reads
  // as breathing, and a faster ripple that only appears while speaking.
  float slow = vnoise(n * 1.7 + vec3(0.0, uTime * 0.22, 0.0)) - 0.5;
  float fast = vnoise(n * 5.5 + vec3(uTime * 0.9, 0.0, uTime * 0.6)) - 0.5;

  float breathe = slow * (0.06 + uAwake * 0.05);
  float speech = fast * uLevel * 0.22;
  float displace = breathe + speech;

  vec3 pos = position + n * displace;

  vDisplace = displace;
  vNormal = normalize(normalMatrix * n);
  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

export const PRESENCE_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform vec3 uHot;
uniform float uLevel;
uniform float uAwake;

varying vec3 vNormal;
varying vec3 vView;
varying float vDisplace;

void main() {
  float facing = 1.0 - abs(dot(normalize(vNormal), normalize(vView)));
  float rim = pow(facing, 2.2);

  // Peaks of the displacement run hot; troughs stay in the interface blue.
  float heat = clamp(vDisplace * 6.0 + uLevel * 0.5, 0.0, 1.0);
  vec3 color = mix(uColor, uHot, heat);

  // Mostly a rim: a solid sphere in the middle of the room would read as an
  // object, and this is meant to read as a presence.
  float alpha = (rim * (0.4 + uAwake * 0.5) + heat * 0.35) * (0.25 + uAwake * 0.75);
  if (alpha < 0.003) discard;

  gl_FragColor = vec4(color * (0.7 + rim * 1.3 + heat), alpha);
}
`;
