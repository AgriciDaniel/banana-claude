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
/** How many plate divisions run along this part. 0 leaves the surface bare. */
uniform float uPlates;
/** 1 for a hard shell, 0 for the suit under it. */
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
   * Scan lines, scrolling slowly downward. They were fine on a bare body and
   * wrong the moment it had plating: fifty-six horizontal lines crossing the
   * new vertical seams turned the whole figure into wire mesh. Coarser now, and
   * barely present -- they are a texture on the light, not a pattern to read.
   */
  float scan = 0.5 + 0.5 * sin((vHeight - uTime * 0.31) * 24.0);

  // The feet do not end, they stop being. Anything else needs a floor contact
  // this figure has no business claiming.
  float rise = smoothstep(uFootY, uFootY + 0.46, vHeight);

  // Speaking pushes light into the rim rather than raising the whole body:
  // brightening everything would read as a lamp, brightening the edge reads
  // as the thing itself being driven.
  float speech = uLevel * 0.34 * rim;

  /*
   * The skin.
   *
   * A body of plain glowing profiles reads as a ghost, and a ghost cannot look
   * like a machine that belongs to this interface. So the surface is divided:
   * plates running along each limb, a seam where they meet, and two seams
   * running down the length. All of it comes from the lathe's own UVs -- v
   * along the bone, u around it -- so it costs no texture and no asset, and it
   * follows the geometry exactly however the profile changes width.
   *
   * The seams glow rather than darken. A dark line on an additive surface is
   * invisible; a bright one is the whole point.
   */
  float alongPlate = fract(vUv.y * uPlates);
  float plateEdge = smoothstep(0.028, 0.0, min(alongPlate, 1.0 - alongPlate));
  float around = abs(fract(vUv.x * 2.0 + 0.25) - 0.5) * 2.0;
  float sideSeam = smoothstep(0.978, 1.0, around);
  float seam = max(plateEdge, sideSeam) * step(0.5, uPlates);

  /*
   * The shell catches light across its whole face; the suit underneath only
   * catches it at the edges. That one difference is what separates an armoured
   * forearm from the torso it hangs beside.
   */
  float body = mix(0.04, 0.12, uShell);

  vec3 tint = mix(uColor, uHot, rim * 0.7 + uLevel * 0.2 + seam * 0.85);

  /*
   * Kept deliberately dim. Eleven capsules drawn additively overlap wherever a
   * limb crosses the torso, and the scene's bloom is generous: values that look
   * reasonable on one surface become a lamp once three of them stack up.
   */
  float alpha = (body + rim * 0.78 + scan * 0.014 + seam * 0.34 + speech) * rise * uPresence;

  gl_FragColor = vec4(tint * (0.6 + rim * 0.8 + seam * 0.55 + uLevel * 0.2), alpha);
}
`;
