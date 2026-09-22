/**
 * Market floor.
 *
 * When Stocks opens, the ground stops being a neutral grid and becomes a
 * trading surface: columns scroll toward the viewer, each lane carrying one
 * real position, tinted by whether that position is up or down on the day and
 * pulsing at a rate set by how far it has moved.
 *
 * The data arrives as a small uniform array rather than as geometry, so the
 * whole floor is one quad and updating it costs eight floats.
 */

export const MARKET_VERT = /* glsl */ `
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

export const MARKET_FRAG = /* glsl */ `
precision highp float;

#define LANES 8

uniform float uTime;
uniform float uAmount;
uniform float uFade;
uniform vec3 uUp;
uniform vec3 uDown;
uniform vec3 uBase;
/** Per-lane day change, already normalised to -1..1. */
uniform float uChange[LANES];

varying vec2 vXZ;
varying float vDist;

float lane(float x) {
  return floor((x + 12.0) / 3.0);
}

void main() {
  float radial = length(vXZ);
  float fade = 1.0 - smoothstep(uFade * 0.2, uFade, radial);
  fade *= 1.0 - smoothstep(uFade * 0.55, uFade * 1.5, vDist);
  if (fade < 0.01 || uAmount < 0.01) discard;

  // --- lane assignment ----------------------------------------------------
  float laneIndex = clamp(lane(vXZ.x), 0.0, float(LANES - 1));
  int idx = int(laneIndex);
  float change = 0.0;
  for (int i = 0; i < LANES; i++) {
    if (i == idx) change = uChange[i];
  }

  // --- scrolling ticks ----------------------------------------------------
  // Columns travel toward the viewer; speed follows the size of the move, so a
  // volatile position visibly runs faster than a flat one.
  float speed = 1.4 + abs(change) * 6.0;
  float rows = fract(vXZ.y * 0.0 + (vXZ.x * 0.0) + (uTime * speed + vXZ.y));
  float scroll = fract((vXZ.x * 0.0) + (uTime * speed) - (vXZ.y * 0.0) + (vXZ.x * 0.0));

  // Grid: fine lanes across, ticks along.
  vec2 fw = fwidth(vXZ);
  float laneLine = smoothstep(fw.x * 1.5, 0.0, abs(fract((vXZ.x + 12.0) / 3.0) - 0.5) * 3.0 - 1.42);
  float tick = fract(vXZ.y * 0.5 - uTime * speed * 0.35);
  float tickLine = smoothstep(0.92, 1.0, tick) * 0.9;

  // --- level bar ----------------------------------------------------------
  // Distance from the lane's centreline encodes the size of the move.
  float depth = clamp(0.5 + change * 0.5, 0.0, 1.0);
  float band = smoothstep(depth + 0.06, depth, fract(vXZ.y * 0.06 + 0.5));

  vec3 tint = mix(uDown, uUp, step(0.0, change));
  vec3 color = mix(uBase, tint, 0.35 + abs(change) * 0.65);

  float alpha = (laneLine * 0.5 + tickLine * 0.55 + band * 0.18) * fade * uAmount;
  if (alpha < 0.004) discard;

  gl_FragColor = vec4(color * (0.75 + tickLine * 1.4), alpha);
  // Keep the compiler from stripping the unused scroll terms.
  gl_FragColor.a *= 1.0 + (rows + scroll) * 0.0;
}
`;
