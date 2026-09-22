/**
 * Wake wave.
 *
 * A shell of light that leaves the centre of the room and passes through
 * everything. Rendered as an expanding sphere with a grazing-angle falloff, so
 * what the viewer actually sees is a thin travelling front rather than a
 * ballooning solid - the cheapest convincing way to make a room announce that
 * something in it has just come alive.
 */

export const WAKE_VERT = /* glsl */ `
varying vec3 vNormal;
varying vec3 vView;

void main() {
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}
`;

export const WAKE_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform float uProgress;
uniform float uIntensity;

varying vec3 vNormal;
varying vec3 vView;

void main() {
  // Grazing angles only: the shell reads as a surface passing through the
  // room, not as a glowing balloon.
  float facing = 1.0 - abs(dot(normalize(vNormal), normalize(vView)));
  float rim = pow(facing, 2.6);

  // Fade in fast, fade out slowly, so the front is sharp and the wake is soft.
  float envelope = smoothstep(0.0, 0.08, uProgress) * (1.0 - smoothstep(0.25, 1.0, uProgress));

  float alpha = rim * envelope * uIntensity;
  if (alpha < 0.002) discard;

  gl_FragColor = vec4(uColor * (1.0 + rim), alpha);
}
`;

/** Ground ripple that travels outward under the ring at the same moment. */
export const RIPPLE_FRAG = /* glsl */ `
precision highp float;

uniform vec3 uColor;
uniform float uProgress;
uniform float uRadius;
uniform float uIntensity;

varying vec2 vUv;

void main() {
  vec2 p = (vUv - 0.5) * 2.0;
  float d = length(p) * uRadius;

  float front = uProgress * uRadius;
  // A narrow band that widens slightly as it travels, like a real wavefront.
  float width = 0.35 + uProgress * 1.6;
  float band = exp(-pow((d - front) / width, 2.0));

  float envelope = (1.0 - smoothstep(0.55, 1.0, uProgress)) * step(d, uRadius);
  float alpha = band * envelope * uIntensity * 0.55;
  if (alpha < 0.002) discard;

  gl_FragColor = vec4(uColor * (0.8 + band), alpha);
}
`;

export const RIPPLE_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;
