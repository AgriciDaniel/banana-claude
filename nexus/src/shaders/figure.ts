/**
 * The assistant's body, as light.
 *
 * A figure that shows you things has to be legible from across the room and
 * has to not look like a person. Both are solved by the same material: the
 * surface is almost transparent where it faces you and bright where it turns
 * away, so what you read is the *silhouette and the pose* -- an arm extended,
 * a head turned -- and never a face pretending to be one.
 *
 * Drawn additively with no depth write, so overlapping limbs brighten where
 * they cross. That is what gives a shape made of eleven capsules any sense of
 * volume at all, and it removes the sorting problem a transparent body has
 * with its own arms.
 */

export const FIGURE_VERT = /* glsl */ `
varying vec3 vNormal;
varying vec3 vView;
varying float vHeight;
varying vec2 vUv;

void main() {
  vUv = uv;
  vec4 world = modelMatrix * vec4(position, 1.0);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);

  vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  // World height, not local: the scan lines and the dissolve have to belong to
  // the room, so they stay put while a limb swings through them.
  vHeight = world.y;

  gl_Position = projectionMatrix * mv;
}
`;

export const FIGURE_FRAG = /* glsl */ `
uniform float uTime;
uniform float uLevel;
uniform float uPresence;
uniform float uFootY;
uniform vec3 uColor;
uniform vec3 uHot;
/** Contour rings per world unit of height. 0 leaves the surface bare. */
uniform float uRings;
/** How solidly this part catches light across its face, not just at its edge. */
uniform float uShell;

varying vec3 vNormal;
varying vec3 vView;
varying float vHeight;
varying vec2 vUv;

void main() {
  /*
   * Absolute, not clamped. The body is drawn double-sided so you see through
   * it to its own far surface, and a back face arrives with its normal turned
   * around: clamping the dot product to zero gave every one of them a rim term
   * of exactly 1, so the whole inside of every limb burned at full strength and
   * the figure came out as a single white streak.
   */
  float facing = abs(dot(normalize(vNormal), normalize(vView)));
  // Rim light. The whole read of the figure lives in this one term.
  float rim = pow(1.0 - facing, 1.7);

  /*
   * Contour rings -- the whole surface treatment, and the thing that makes a
   * body read as a body rather than as a machine.
   *
   * Cut in WORLD height, not along the geometry, so they stay level while a
   * limb swings through them: the figure is read the way a scanner reads it,
   * in slices. That is exactly what a holographic body looks like, and it is
   * what plating could never be -- plates divide a form into parts, contours
   * describe one continuous form.
   *
   * Raised to a high power so each ring is a thin bright line with dark
   * between, instead of a soft stripe.
   */
  float wave = 0.5 + 0.5 * sin((vHeight - uTime * 0.04) * uRings);
  float contour = pow(wave, 11.0) * step(0.5, uRings);

  /*
   * The feet fade, but only just. They used to dissolve over half the lower
   * leg, which was right while the figure hovered over nothing; standing on a
   * projector it needs ankles, and the dais gives it the floor contact the
   * fade was standing in for.
   */
  float rise = smoothstep(uFootY - 0.02, uFootY + 0.13, vHeight);

  // Speaking pushes light into the rim rather than raising the whole body:
  // brightening everything would read as a lamp, brightening the edge reads
  // as the thing itself being driven.
  float speech = uLevel * 0.34 * rim;

  /*
   * A seam down each side, faint. One line where a surface closes on itself is
   * enough to say the form was built rather than grown; two dozen of them said
   * "robot", which is not what this is.
   */
  float around = abs(fract(vUv.x * 2.0 + 0.25) - 0.5) * 2.0;
  float seam = smoothstep(0.984, 1.0, around) * uShell;

  float body = mix(0.03, 0.075, uShell);

  vec3 tint = mix(uColor, uHot, rim * 0.62 + uLevel * 0.2 + contour * 0.8);

  /*
   * Kept deliberately dim. Eleven capsules drawn additively overlap wherever a
   * limb crosses the torso, and the scene's bloom is generous: values that look
   * reasonable on one surface become a lamp once three of them stack up.
   */
  float alpha = (body + rim * 0.74 + contour * 0.42 + seam * 0.14 + speech) * rise * uPresence;

  gl_FragColor = vec4(tint * (0.52 + rim * 0.82 + contour * 0.7 + uLevel * 0.2), alpha);
}
`;

/**
 * The face, and the one thing it has to solve.
 *
 * A generated frame is a rectangle, and the body is drawn additively, so any
 * value the model left in the corners of that rectangle adds to the scene --
 * the first version hung a visible bright square around the face. Nothing in
 * the image is wrong; a rectangle simply cannot end abruptly on an additive
 * surface.
 *
 * So the edges are taken out here rather than in the file: a soft elliptical
 * mask over the frame, wider than it is tall because a face is. Doing it in
 * the shader keeps the generated image untouched and unprocessed, which means
 * regenerating one is still just `npm run make:face`.
 */

export const FACE_VERT = /* glsl */ `
varying vec2 vUv;

void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const FACE_FRAG = /* glsl */ `
uniform sampler2D uMap;
uniform vec2 uOffset;
uniform vec2 uRepeat;
uniform float uOpacity;

varying vec2 vUv;

void main() {
  // Crop and mirror, applied here so the mask can stay in frame space.
  vec3 rgb = texture2D(uMap, vUv * uRepeat + uOffset).rgb;

  vec2 d = (vUv - 0.5) * vec2(2.2, 1.92);
  float mask = 1.0 - smoothstep(0.66, 1.0, length(d));

  // Additive: the contribution is colour times alpha, so the mask rides there.
  gl_FragColor = vec4(rgb, mask * uOpacity);
}
`;
