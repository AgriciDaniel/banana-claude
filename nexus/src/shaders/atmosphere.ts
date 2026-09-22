import { NOISE, TONEMAP } from './common';

/**
 * The room itself.
 *
 * There are no walls. What reads as "a space" is a large inward-facing sphere
 * carrying a slow fbm fog field plus a horizon gradient, rendered on the back
 * side with depth-write off. It is infinite in the only sense that matters:
 * you can never reach it, and it never repeats visibly.
 */

export const ATMOSPHERE_VERT = /* glsl */ `
varying vec3 vDir;
varying vec3 vWorld;

void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  vDir = normalize(position);
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

export const ATMOSPHERE_FRAG = /* glsl */ `
precision highp float;

uniform float uTime;
uniform vec3 uDeep;
uniform vec3 uMid;
uniform vec3 uGlow;
uniform float uDensity;
uniform float uFreeze;
/** Height and weight of the horizon band. Environments differ most here. */
uniform float uHorizon;

varying vec3 vDir;
varying vec3 vWorld;

${NOISE}
${TONEMAP}

void main() {
  float t = uTime * mix(1.0, 0.05, uFreeze);
  vec3 d = normalize(vDir);

  // Two fog layers drifting at different rates and scales. The difference in
  // their speeds is what stops the volume looking like a static matte.
  float f1 = fbm(d * 2.1 + vec3(0.0, t * 0.014, t * 0.008));
  float f2 = fbm(d * 5.3 - vec3(t * 0.011, 0.0, t * 0.006));
  float fog = mix(f1, f2, 0.45);

  // Vertical structure: dense floor haze, clear overhead.
  float h = d.y * 0.5 + 0.5;
  float floorHaze = pow(1.0 - h, 2.6);
  float ceiling = pow(h, 3.4) * 0.35;

  vec3 color = mix(uDeep, uMid, fog * uDensity + floorHaze * 0.55);

  // A cold overhead pool - the implied light source everything else agrees with.
  float pool = pow(max(d.y, 0.0), 6.0);
  color += uGlow * pool * 0.30;

  // Horizon band, offset slightly below eye level so the space feels seated.
  float band = exp(-pow((d.y + 0.06) * mix(7.5, 3.2, clamp(uHorizon, 0.0, 1.6) / 1.6), 2.0));
  color += uGlow * band * 0.055 * uHorizon * (0.6 + fog * 0.8);

  color += uMid * ceiling * 0.2;

  // Subtle chromatic depth: the far field cools off, keeping blue dominant.
  color.b *= 1.06;
  color.r *= 0.94;

  gl_FragColor = vec4(softClip(color), 1.0);
}
`;

/**
 * Infinite ground plane.
 *
 * There is no floor object - this is a grid fading into the fog, which reads
 * as ground without ever committing to a surface you could stand on.
 */
export const GRID_VERT = /* glsl */ `
varying vec2 vXZ;
varying float vDist;

void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vXZ = world.xz;
  vec4 mv = viewMatrix * world;
  vDist = -mv.z;
  gl_Position = projectionMatrix * mv;
}
`;

export const GRID_FRAG = /* glsl */ `
precision highp float;

uniform float uTime;
uniform vec3 uColor;
uniform float uSpacing;
uniform float uFade;
uniform float uFreeze;
uniform float uStrength;

varying vec2 vXZ;
varying float vDist;

// Analytically antialiased grid: line width tracks screen-space derivative,
// so distant lines dissolve instead of aliasing into moire.
float gridLine(vec2 p, float spacing, float thickness) {
  vec2 g = abs(fract(p / spacing - 0.5) - 0.5) * spacing;
  vec2 fw = fwidth(p) * thickness;
  vec2 line = smoothstep(fw, vec2(0.0), g);
  return max(line.x, line.y);
}

void main() {
  float t = uTime * mix(1.0, 0.05, uFreeze);

  float fine = gridLine(vXZ, uSpacing, 1.2) * 0.35;
  float coarse = gridLine(vXZ, uSpacing * 5.0, 1.6) * 0.7;
  float g = max(fine, coarse);

  float radial = length(vXZ);
  float fade = 1.0 - smoothstep(uFade * 0.25, uFade, radial);
  fade *= 1.0 - smoothstep(uFade * 0.6, uFade * 1.6, vDist);

  // A slow ring of light travelling outward - a heartbeat for the floor.
  float ring = exp(-pow((radial - fract(t * 0.035) * uFade) * 0.5, 2.0)) * 0.5;

  float alpha = (g * 0.3 + ring * g * 1.1) * fade * uStrength;
  if (alpha < 0.002) discard;

  gl_FragColor = vec4(uColor * (0.7 + ring * 1.4), alpha);
}
`;
