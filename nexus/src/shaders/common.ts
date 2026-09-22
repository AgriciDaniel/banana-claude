/**
 * GLSL fragments shared across the environment shaders.
 * Kept as strings rather than files so they inline cleanly in the bundle and
 * survive Next's module graph without a loader.
 */

/** Cheap 3D hash + value noise + 4-octave fbm. */
export const NOISE = /* glsl */ `
float hash13(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}

float vnoise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash13(i);
  float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
  float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
  float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
  float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
  float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
  float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
  float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
  return mix(
    mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
    mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
    f.z
  );
}

float fbm(vec3 p) {
  float sum = 0.0;
  float amp = 0.5;
  for (int i = 0; i < 4; i++) {
    sum += vnoise(p) * amp;
    p *= 2.02;
    amp *= 0.5;
  }
  return sum;
}
`;

/** Divergence-free-ish drift field. Gives particles their living motion. */
export const CURL = /* glsl */ `
vec3 curlDrift(vec3 p, float t) {
  float s = 0.42;
  vec3 a = vec3(
    vnoise(p * s + vec3(0.0, t * 0.11, 0.0)),
    vnoise(p * s + vec3(5.2, 1.3 + t * 0.09, 2.7)),
    vnoise(p * s + vec3(9.4, 4.7, 6.1 - t * 0.07))
  );
  return (a - 0.5) * 2.0;
}
`;

/** Exponential-squared depth fade matching the scene fog. */
export const FOG = /* glsl */ `
float fogFactor(float dist, float near, float far) {
  return 1.0 - smoothstep(near, far, dist);
}
`;

/** sRGB-ish tone shaping so additive layers do not blow out to white. */
export const TONEMAP = /* glsl */ `
vec3 softClip(vec3 c) {
  return c / (1.0 + max(max(c.r, c.g), c.b) * 0.45);
}
`;
