'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  Quaternion,
  ShaderMaterial,
  Vector3,
  type Group,
  type Mesh,
} from 'three';
import { FIGURE_FRAG, FIGURE_VERT } from '@/shaders/figure';
import { PALETTE } from '@/config/theme';
import { attention, interaction, voice } from '@/stores/runtime';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { clamp01, damp, noise1 } from '@/core/math';
import { FORWARD, HEAD_CONE, REST_DIR, RIG, aimAt, boneArgs, clampToCone } from './rig';
import { figureReport } from './report';

/**
 * The assistant, with a body.
 *
 * The orb at the centre of the ring says something is present and listening.
 * It cannot say *look at that one*. A figure can: it turns, it reaches, and
 * the thing at the end of its arm is the thing being talked about. That is the
 * whole justification for it, and it is why almost everything here is driven
 * by one world point -- `attention` -- rather than by a library of animations.
 *
 * Three rules held throughout:
 *
 *   - It indicates, it does not perform. No walking, no acting out. The only
 *     large movement it ever makes is toward something it is showing you.
 *   - It is made of light, not of anatomy. Eleven capsules and a sphere, drawn
 *     additively. Nothing here should read as a person in the room; it should
 *     read as the interface having a direction to gesture in.
 *   - The mouth is a level meter, honestly. It opens on the speech envelope
 *     that is actually playing, so it can never mime words that were not said.
 */

/**
 * Where it stands.
 *
 * To the viewer's left of the media row and a little nearer than it, so that
 * pointing at a panel is a movement *into* the scene rather than across the
 * viewer's line of sight. Standing behind the row would put the arm through
 * the panels; standing in front of it would put the body over them.
 */
const HOME: [number, number, number] = [-2.2, -0.05, 6.6];

/**
 * How big it stands.
 *
 * The rig is written in human proportions because that is the only way its
 * numbers stay meaningful, but a life-sized figure at the depth the panels
 * occupy fills the frame from top to bottom -- measured, not guessed: at the
 * first placement it came out 740 pixels tall in a 555 pixel viewport.
 *
 * Scaled down here rather than in the rig, so the proportions stay readable
 * and the size stays one number. A projected figure a little under a metre,
 * standing beside content taller than itself, is also simply the right image:
 * it presents the room, it does not occupy it.
 */
const FIGURE_SCALE = 0.62;
/**
 * Standing down.
 *
 * A module expanding pushes the media row left, into exactly the ground the
 * figure was holding -- measured with a chart open, the panel spanned x = -3.4
 * to -0.8 and the figure was standing at -2.7, in front of its own content.
 *
 * So it does not merely sidestep, it withdraws: further left, further back,
 * and dimmer. When you open a module you are reading it, not being presented
 * to, and a presenter who will not get out of the way of the thing it just
 * showed you is worse than no presenter at all.
 */
const ASIDE: [number, number, number] = [-3.05, -0.05, 6.0];
/** How much presence it keeps while a module holds the frame. */
const ASIDE_PRESENCE = 0.55;

/** Below this the stage has nothing worth turning toward. */
const POINT_THRESHOLD = 0.35;

/** How much of the head's turn the shoulders follow. */
const TORSO_FOLLOW = 0.42;

const tmpTarget = new Vector3();
const tmpProject = new Vector3();
const tmpDir = new Vector3();
const tmpFrom = new Vector3();
const swing = new Quaternion();
const rest = new Quaternion();

export function Figure() {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const tier = useSystemStore((s) => s.profile.tier);
  const status = useAssistantStore((s) => s.status);
  const expandedId = useCarouselStore((s) => s.expandedId);

  const group = useRef<Group>(null);
  const root = useRef<Group>(null);
  const chest = useRef<Group>(null);
  const head = useRef<Group>(null);
  const mouth = useRef<Mesh>(null);
  const eyes = useRef<Group>(null);
  const shoulderL = useRef<Group>(null);
  const shoulderR = useRef<Group>(null);
  const elbowL = useRef<Group>(null);
  const elbowR = useRef<Group>(null);

  // Coarse tiers drop segments: at this size, and this transparent, the
  // silhouette carries everything and the facets never show.
  const segments = tier === 'low' ? 8 : tier === 'medium' ? 10 : 14;

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLevel: { value: 0 },
      uPresence: { value: 0 },
      uFootY: { value: HOME[1] + RIG.footY * FIGURE_SCALE },
      uColor: { value: new Color(PALETTE.core) },
      uHot: { value: new Color(PALETTE.signal) },
    }),
    [],
  );

  /*
   * One material instance for the whole body, constructed here and handed to
   * every mesh by prop.
   *
   * Declaring it as JSX and reusing the element did not work: the meshes came
   * out with no material at all and simply were not drawn -- the face, which
   * uses ordinary basic materials, rendered on its own in mid-air exactly where
   * the head should have been. Building the material and passing it is also
   * what the comment always claimed was happening: one instance, one set of
   * uniforms, written once per frame.
   */
  const material = useMemo(
    () =>
      new ShaderMaterial({
        vertexShader: FIGURE_VERT,
        fragmentShader: FIGURE_FRAG,
        uniforms,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: DoubleSide,
      }),
    [uniforms],
  );
  useEffect(() => () => material.dispose(), [material]);

  const place = useMemo(() => new Spring3(HOME, SPRINGS.glide), []);
  const presence = useMemo(() => new Spring(0, SPRINGS.glide), []);
  /** How committed the pose is to indicating something. */
  const showing = useMemo(() => new Spring(0, SPRINGS.glide), []);
  const jaw = useMemo(() => new Spring(0, SPRINGS.flash), []);

  const blink = useRef({ next: 2.4, until: 0 });

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const time = interaction.sceneTime;

    /*
     * Present when the assistant is awake, and also whenever something is
     * standing on the stage. The second half matters more than it looks: a
     * panel can arrive from a typed question with the microphone never having
     * opened, and a figure that is not there cannot point at it.
     */
    const wanted =
      Math.max(voice.awakeBlend, attention.weight) * (expandedId ? ASIDE_PRESENCE : 1);
    presence.set(wanted).update(dt);
    const here = presence.value;

    const target = attention.weight > POINT_THRESHOLD;
    showing.set(target ? attention.weight : 0).update(dt);
    const show = showing.value;

    uniforms.uTime.value = time;
    uniforms.uLevel.value = voice.level;
    uniforms.uPresence.value = here;

    figureReport.presence = here;
    figureReport.showing = show;
    figureReport.looking = target ? 'stage' : 'viewer';

    if (!group.current) return;
    if (here < 0.004) {
      group.current.visible = false;
      return;
    }
    group.current.visible = true;

    const home = expandedId ? ASIDE : HOME;
    place.set(home[0], home[1], home[2]).update(dt);
    group.current.position.set(place.x.value, place.y.value, place.z.value);
    uniforms.uFootY.value = place.y.value + RIG.footY * FIGURE_SCALE;

    /*
     * Squared up to the viewer, wherever the viewer happens to be.
     *
     * The figure stands well off to one side, so a body built facing +Z faces
     * slightly away from the seat -- and then has to turn ninety degrees at the
     * neck to look at a panel, which the head cone will not allow and should
     * not. Turning the whole body to face the camera first puts the head's
     * remaining turn inside its limits and reads, correctly, as someone
     * addressing you rather than staring past you.
     */
    group.current.rotation.y = damp(
      group.current.rotation.y,
      Math.atan2(camera.position.x - place.x.value, camera.position.z - place.z.value),
      3,
      dt,
    );

    /*
     * Breathing. Barely there on purpose -- the point is that the figure is
     * never perfectly still, not that you can watch it breathe. A second,
     * slower drift keeps two idle moments from looking identical.
     */
    if (root.current) {
      root.current.position.y = Math.sin(time * 1.35) * 0.006 + noise1(time * 0.21) * 0.012;
      root.current.rotation.z = noise1(time * 0.17 + 4) * 0.02;
    }

    // What it is looking at: the thing on stage, or you.
    if (target) {
      tmpTarget.set(attention.x, attention.y, attention.z);
    } else {
      tmpTarget.copy(camera.position);
    }

    // --- Head ------------------------------------------------------------
    let headYaw = 0;
    if (head.current) {
      head.current.getWorldPosition(tmpFrom);
      tmpDir.copy(tmpTarget).sub(tmpFrom);
      if (tmpDir.lengthSq() > 1e-8) {
        tmpDir.normalize();
        const parent = head.current.parent;
        if (parent) {
          parent.getWorldQuaternion(swing).invert();
          tmpDir.applyQuaternion(swing);
        }
        clampToCone(tmpDir, FORWARD, HEAD_CONE);
        swing.setFromUnitVectors(FORWARD, tmpDir);
        head.current.quaternion.slerp(swing, 1 - Math.exp(-6 * dt));
        headYaw = Math.atan2(tmpDir.x, tmpDir.z);
      }
    }

    /*
     * The shoulders follow part of the way round. Without this the head
     * swivels on a body facing forward, which is the one thing that makes a
     * rig look like a puppet rather than like something paying attention.
     */
    if (chest.current) {
      chest.current.rotation.y = damp(
        chest.current.rotation.y,
        headYaw * TORSO_FOLLOW * show,
        5,
        dt,
      );
      chest.current.rotation.x = damp(chest.current.rotation.x, -0.05 + show * 0.03, 5, dt);
    }

    // --- Arms ------------------------------------------------------------
    /*
     * One arm indicates, the other rests. Which one is decided by where the
     * target is: reaching across the body reads as a stretch rather than as a
     * gesture, so the near arm always takes it.
     */
    const toTheRight = tmpTarget.x > place.x.value;
    const pointer = toTheRight ? shoulderR : shoulderL;
    const pointerElbow = toTheRight ? elbowR : elbowL;
    const idle = toTheRight ? shoulderL : shoulderR;
    const idleElbow = toTheRight ? elbowL : elbowR;
    /*
     * Which SIDE of the body each shoulder is on, not which job it is doing.
     * A rest angle swings an arm outward only if its sign follows the shoulder,
     * and conflating the two put the resting arm through the torso whenever the
     * target happened to be on the other side.
     */
    const pointerSide = toTheRight ? 1 : -1;
    const idleSide = -pointerSide;

    if (pointer.current) {
      aimAt(pointer.current, tmpTarget, REST_DIR, swing);
      /*
       * Resting is not "straight down": a limb hanging on the exact axis reads
       * as switched off. A few degrees out from the body is the pose a person
       * holds without thinking about it.
       */
      rest.setFromAxisAngle(FORWARD, pointerSide * 0.13);
      swing.slerp(rest, 1 - show);
      pointer.current.quaternion.slerp(swing, 1 - Math.exp(-7 * dt));
    }
    if (pointerElbow.current) {
      /*
       * Full extension only for something well off to the side; anything close
       * to straight ahead keeps a bend, because a locked arm aimed at the
       * viewer is a gun barrel and reads as one.
       */
      const sideways = Math.min(1, Math.abs(tmpTarget.x - place.x.value) / 2.4);
      const bend = show * (-0.34 + sideways * 0.26) + (1 - show) * -0.4;
      pointerElbow.current.rotation.x = damp(pointerElbow.current.rotation.x, bend, 6, dt);
    }

    if (idle.current) {
      /*
       * The resting arm is not dead: while the voice runs it swings a little on
       * the speech envelope. Small beats, shoulder only, so it never competes
       * with the arm doing the pointing.
       */
      const beat = voice.level * 0.16 + noise1(time * 0.6 + 11) * 0.05;
      rest.setFromAxisAngle(FORWARD, idleSide * (0.11 + beat * 0.35));
      idle.current.quaternion.slerp(rest, 1 - Math.exp(-5 * dt));
    }
    if (idleElbow.current) {
      idleElbow.current.rotation.x = damp(
        idleElbow.current.rotation.x,
        -0.36 - voice.level * 0.22,
        5,
        dt,
      );
    }

    // --- Mouth -----------------------------------------------------------
    /*
     * Straight off the envelope that is actually playing. Not phonemes, not a
     * guess from the text -- if the audio is silent the mouth is shut, which is
     * the only version of this that cannot mime words nobody said.
     */
    const speaking = status === 'speaking' || status === 'streaming';
    jaw.set(speaking ? clamp01(voice.level * 1.25) : 0).update(dt);
    figureReport.mouth = jaw.value;
    if (mouth.current) {
      const open = jaw.value;
      mouth.current.scale.set(1 - open * 0.22, 0.16 + open * 1.5, 1);
      (mouth.current.material as { opacity: number }).opacity = 0.22 + open * 0.55;
    }

    // --- Eyes ------------------------------------------------------------
    /*
     * A blink costs almost nothing and buys the largest share of whatever life
     * this figure has. Random intervals: a regular blink is a metronome, and a
     * metronome reads as a fault.
     */
    /*
     * Where the body actually landed, in pixels. Measured from the head and
     * the feet rather than assumed from the constants, so a mistake in the
     * placement shows up here instead of only in a screenshot.
     */
    figureReport.x = place.x.value;
    figureReport.y = place.y.value;
    figureReport.z = place.z.value;
    if (head.current) {
      head.current.getWorldPosition(tmpProject);
      tmpProject.project(camera);
      figureReport.screenX = (tmpProject.x * 0.5 + 0.5) * size.width;
      const headPx = (0.5 - tmpProject.y * 0.5) * size.height;
      figureReport.screenY = headPx;
      tmpProject
        .set(place.x.value, place.y.value + RIG.footY * FIGURE_SCALE, place.z.value)
        .project(camera);
      figureReport.screenHeight = (0.5 - tmpProject.y * 0.5) * size.height - headPx;
    }

    if (eyes.current) {
      const b = blink.current;
      if (time > b.next) {
        b.until = time + 0.09;
        b.next = time + 2.2 + Math.random() * 3.6;
      }
      eyes.current.scale.y = time < b.until ? 0.08 : 1;
    }
  });

  const upper = boneArgs(RIG.upperArm, RIG.armRadius, segments);
  const lower = boneArgs(RIG.forearm, RIG.armRadius, segments);
  const thigh = boneArgs(RIG.thigh, RIG.limbRadius, segments);
  const shin = boneArgs(RIG.shin, RIG.limbRadius, segments);
  const torso = boneArgs(RIG.chestY + 0.34, 0.088, segments);
  const neck = boneArgs(0.1, 0.032, segments);


  return (
    <group ref={group} name="assistant-figure" scale={FIGURE_SCALE} visible={false}>
      <group ref={root}>
        {/* Hips and legs. Static: this figure stands, it never walks. */}
        {[-1, 1].map((side) => (
          <group key={side} position={[side * RIG.hipX, 0, 0]} rotation={[0.04, 0, side * 0.03]}>
            <mesh material={material}>
              <sphereGeometry args={[0.05, segments, Math.max(3, segments >> 1)]} />
            </mesh>
            <mesh material={material} position={[0, -RIG.thigh / 2, 0]}>
              <capsuleGeometry args={thigh} />
            </mesh>
            <group position={[0, -RIG.thigh, 0]} rotation={[-0.06, 0, 0]}>
              <mesh material={material}>
                <sphereGeometry args={[0.04, segments, Math.max(3, segments >> 1)]} />
              </mesh>
              <mesh material={material} position={[0, -RIG.shin / 2, 0]}>
                <capsuleGeometry args={shin} />
              </mesh>
            </group>
          </group>
        ))}

        <group ref={chest}>
          <mesh material={material} position={[0, RIG.chestY / 2 + 0.04, 0]}>
            <capsuleGeometry args={torso} />
          </mesh>

          {[
            { key: 'L', side: -1, shoulder: shoulderL, elbow: elbowL },
            { key: 'R', side: 1, shoulder: shoulderR, elbow: elbowR },
          ].map(({ key, side, shoulder, elbow }) => (
            <group
              key={key}
              ref={shoulder}
              position={[side * RIG.shoulderX, RIG.shoulderY, 0]}
            >
              {/*
                Joint balls at the shoulder and the elbow.
                Without them a raised arm reads as a bar floating beside the
                body rather than as a limb attached to it: the capsule swings
                away from the torso and nothing bridges the gap it leaves. They
                cost two spheres and they are the difference between a pointing
                gesture and a detached prop.
              */}
              <mesh material={material}>
                <sphereGeometry args={[0.046, segments, Math.max(3, segments >> 1)]} />
              </mesh>
              <mesh material={material} position={[0, -RIG.upperArm / 2, 0]}>
                <capsuleGeometry args={upper} />
              </mesh>
              <group ref={elbow} position={[0, -RIG.upperArm, 0]}>
                <mesh material={material}>
                  <sphereGeometry args={[0.036, segments, Math.max(3, segments >> 1)]} />
                </mesh>
                <mesh material={material} position={[0, -RIG.forearm / 2, 0]}>
                  <capsuleGeometry args={lower} />
                </mesh>
                {/*
                  The hand. A flattened sphere, no fingers: at this distance
                  fingers are four pixels of noise, and the direction the arm
                  is aimed does everything a pointing finger would.
                */}
                <mesh
                  material={material}
                  position={[0, -RIG.forearm - 0.03, 0]}
                  scale={[1, 1.25, 0.5]}
                >
                  <sphereGeometry args={[0.049, segments, Math.max(3, segments >> 1)]} />
                </mesh>
              </group>
            </group>
          ))}

          <mesh material={material} position={[0, RIG.neckY, 0]}>
            <capsuleGeometry args={neck} />
          </mesh>

          <group ref={head} position={[0, RIG.headY, 0]}>
            <mesh material={material} scale={[0.92, 1, 0.88]}>
              <sphereGeometry args={[RIG.headRadius, segments * 2, segments]} />
            </mesh>

            {/*
              Face. Two marks and a slit, sitting proud of the head so they
              read through it -- deliberately not a face. Anything more
              detailed at this scale lands in the uncanny valley, and this
              figure has no business being mistaken for a person.
            */}
            <group ref={eyes} position={[0, 0.026, RIG.headRadius * 0.82]}>
              {[-1, 1].map((side) => (
                <mesh key={side} position={[side * 0.042, 0, 0]}>
                  <planeGeometry args={[0.026, 0.01]} />
                  <meshBasicMaterial
                    color={PALETTE.lumen}
                    transparent
                    opacity={0.75}
                    depthWrite={false}
                    blending={AdditiveBlending}
                  />
                </mesh>
              ))}
            </group>

            <mesh ref={mouth} position={[0, -0.045, RIG.headRadius * 0.8]}>
              <planeGeometry args={[0.055, 0.028]} />
              <meshBasicMaterial
                color={PALETTE.signal}
                transparent
                opacity={0.22}
                depthWrite={false}
                blending={AdditiveBlending}
              />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
