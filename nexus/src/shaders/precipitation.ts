/**
 * Precipitation.
 *
 * Rain and snow share one shader because they differ only in fall speed,
 * lateral drift and how long a streak they leave. Both are pure functions of
 * (seed, time) in the vertex shader, so weather costs one draw call and no
 * per-frame JavaScript no matter how hard it is coming down.
 *
 * uMode: 0 = rain, 1 = snow.
 */

export const PRECIP_VERT = /* glsl */ `
uniform float uTime;
uniform vec3 uBounds;
uniform float uMode;
uniform float uSpeed;
uniform float uWind;
uniform float uAmount;
uniform float uFreeze;

attribute vec3 aSeed;
attribute float aScale;

varying float vAlpha;
varying float vScale;

void main() {
  float t = uTime * mix(1.0, 0.05, uFreeze);

  vec3 base = aSeed * uBounds;

  // Fall. fract() wraps the column, so a drop that leaves the bottom re-enters
  // at the top with no bookkeeping and no buffer update.
  float speed = uSpeed * (0.6 + aScale * 0.8);
  float fall = fract(aSeed.y * 0.5 + 0.5 - t * speed * 0.06);
  float y = (fall - 0.5) * uBounds.y * 2.0;

  // Snow wanders; rain does not.
  float wander = uMode * sin(t * 0.8 + aSeed.x * 24.0) * 0.55;
  float drift = uWind * (fall * 2.0);

  vec3 pos = vec3(base.x + wander + drift, y, base.z + wander * 0.6);

  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  float dist = -mv.z;

  // Only the first uAmount of the pool is used, so intensity is a uniform
  // rather than a rebuild of the buffer.
  float enabled = step(aScale, uAmount);

  vAlpha = enabled * smoothstep(0.5, 4.0, dist) * (1.0 - smoothstep(16.0, 30.0, dist));
  vScale = mix(1.0, 2.2, uMode);

  gl_Position = projectionMatrix * mv;
  gl_PointSize = mix(1.6, 3.4, uMode) * aScale * (240.0 / max(dist, 0.001));
}
`;

export const PRECIP_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform float uMode;
uniform float uOpacity;

varying float vAlpha;
varying float vScale;

void main() {
  vec2 uv = gl_PointCoord - 0.5;

  // Rain is a vertical streak, snow is a round flake. Stretching the point
  // coordinate is cheaper than a second geometry and reads correctly at speed.
  vec2 shaped = vec2(uv.x * mix(4.5, 1.0, uMode), uv.y);
  float r = dot(shaped, shaped) * 4.0;
  if (r > 1.0) discard;

  float body = pow(1.0 - r, mix(1.4, 2.4, uMode));
  float alpha = body * vAlpha * uOpacity;
  if (alpha < 0.004) discard;

  gl_FragColor = vec4(uColor, alpha);
}
`;
