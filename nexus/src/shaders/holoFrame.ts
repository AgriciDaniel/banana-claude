/**
 * Card frame + surface sheen.
 *
 * Drawn on a plane a hair in front of the glass slab. Everything is signed
 * distance fields, so the border stays pixel-crisp at any distance and any
 * card scale - no texture, no mipmap shimmer, no resolution ceiling.
 *
 * uState drives the whole thing:
 *   0 idle . 1 hovered . 2 focused . 3 selected . 4 dragging . 5 expanded
 * It is a float, not an int, so the frame CROSSFADES between state looks
 * instead of snapping - the spring driving it is what you actually see.
 */

export const FRAME_VERT = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const FRAME_FRAG = /* glsl */ `
precision highp float;

uniform float uTime;
uniform vec2 uSize;
uniform float uRadius;
uniform vec3 uColor;
uniform vec3 uAccent;
uniform float uEnergy;
uniform float uSelect;
uniform float uWarn;
uniform float uFreeze;
uniform float uAspect;
/**
 * Ripple. uRipple is seconds since the strike, negative when idle; uRippleAt
 * is where on the surface it was struck, in uv. Touching a card should make
 * the glass answer, and the cheapest honest answer is a wave from the point of
 * contact.
 */
uniform float uRipple;
uniform vec2 uRippleAt;

varying vec2 vUv;

float sdRoundBox(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return min(max(q.x, q.y), 0.0) + length(max(q, 0.0)) - r;
}

// Perimeter parameter in [0,1) - lets a pulse travel the outline evenly.
float perimeterT(vec2 p, vec2 b) {
  vec2 n = p / b;
  float a = atan(n.y, n.x);
  return (a + 3.14159265) / 6.28318530;
}

void main() {
  float t = uTime * mix(1.0, 0.05, uFreeze);

  vec2 p = (vUv - 0.5) * uSize;
  vec2 half2 = uSize * 0.5;
  float d = sdRoundBox(p, half2 - vec2(0.012), uRadius);

  // --- hairline outline -------------------------------------------------
  float lineW = mix(0.0035, 0.0062, uEnergy);
  float outline = 1.0 - smoothstep(lineW, lineW + 0.0035, abs(d));

  // --- travelling energy pulse -----------------------------------------
  float pt = perimeterT(p, half2);
  float head = fract(t * 0.28 + uSelect * 0.5);
  float along = fract(pt - head);
  float pulse = pow(1.0 - along, 26.0) + pow(1.0 - fract(along + 0.5), 40.0) * 0.35;
  float pulseBand = outline * pulse * (0.35 + uEnergy * 1.9);

  // --- corner brackets --------------------------------------------------
  vec2 ap = abs(p);
  vec2 corner = half2 - vec2(0.055);
  float armX = step(corner.x, ap.x) * step(ap.y, half2.y - 0.012) * step(half2.y - 0.19, ap.y);
  float armY = step(corner.y, ap.y) * step(ap.x, half2.x - 0.012) * step(half2.x - 0.15, ap.x);
  float bracket = clamp(armX + armY, 0.0, 1.0) * (1.0 - smoothstep(0.0, 0.02, abs(d)));
  bracket *= 0.45 + uEnergy * 0.8;

  // --- interior surface treatment ---------------------------------------
  float inside = 1.0 - smoothstep(-0.004, 0.006, d);

  // Fine scanlines, resolution-independent, gated by energy.
  float scan = sin((vUv.y * uSize.y) * 210.0 - t * 1.4) * 0.5 + 0.5;
  float scanline = pow(scan, 8.0) * 0.05 * (0.25 + uEnergy);

  // Diagonal sheen sweep - the "glass catching a light" pass.
  float sweepPos = fract(t * 0.11 + uSelect * 0.25);
  float sweep = vUv.x * 0.6 + vUv.y * 0.4;
  float sheen = exp(-pow((sweep - sweepPos) * 7.5, 2.0)) * (0.05 + uEnergy * 0.16);

  // Vertical falloff so the plate reads as lit from above.
  float grad = mix(0.16, 0.03, vUv.y);

  // --- ripple -----------------------------------------------------------
  float ripple = 0.0;
  if (uRipple >= 0.0 && uRipple < 1.2) {
    // Correct for the card's aspect so the wave is round, not oval.
    vec2 delta = (vUv - uRippleAt) * vec2(uSize.x / uSize.y, 1.0);
    float dist = length(delta);
    float front = uRipple * 1.15;
    float band = exp(-pow((dist - front) / 0.075, 2.0));
    // Fades with both age and distance travelled: energy spreads out.
    ripple = band * (1.0 - uRipple / 1.2) * (1.0 - smoothstep(0.0, 1.1, dist));
  }

  vec3 tint = mix(uColor, uAccent, uWarn);
  vec3 rgb = vec3(0.0);
  float alpha = 0.0;

  rgb += tint * outline * (0.55 + uEnergy * 1.1);
  alpha += outline * (0.5 + uEnergy * 0.45);

  rgb += tint * pulseBand * 2.4;
  alpha += pulseBand * 0.9;

  rgb += tint * bracket * 1.6;
  alpha += bracket * 0.8;

  rgb += tint * inside * (scanline + sheen + grad * 0.35);
  alpha += inside * (scanline + sheen + grad) * 0.75;

  // The wave brightens the plate and briefly lifts the outline it crosses.
  rgb += mix(tint, vec3(1.0), 0.45) * ripple * 1.9;
  alpha += ripple * (inside * 0.85 + outline * 0.6);

  if (alpha < 0.002) discard;
  gl_FragColor = vec4(rgb, clamp(alpha, 0.0, 1.0));
}
`;
