'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  MeshBasicMaterial,
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
import { FORWARD, HEAD_CONE, REST_DIR, RIG, aimAt, clampToCone } from './rig';
import { HAND_POINTING, HAND_RELAXED, buildBody, type FingerPlace } from './body';
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
 *   - It is made of light, not of anatomy. Lathed profiles and a rim-lit
 *     shader: a silhouette and a pose, never a face pretending to be one.
 *   - The mouth moves while it is delivering speech, and only then.
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
const FIGURE_SCALE = 0.68;

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

/**
 * How present it is with nothing to do.
 *
 * It used to appear only on waking, which meant that most of the time the
 * assistant had no body at all -- and a presence you have to summon before you
 * can see it is not a presence. So it stands there, dim, once the room has
 * booted, and comes up to full when it is spoken to or has something to show.
 */
const IDLE_PRESENCE = 0.5;

/** Below this the stage has nothing worth turning toward. */
const POINT_THRESHOLD = 0.35;

/** How much of the head's turn the shoulders follow. */
const TORSO_FOLLOW = 0.42;

const tmpTarget = new Vector3();
const tmpDir = new Vector3();
const tmpFrom = new Vector3();
const tmpProject = new Vector3();
const swing = new Quaternion();
const rest = new Quaternion();

export function Figure() {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const tier = useSystemStore((s) => s.profile.tier);
  const boot = useSystemStore((s) => s.boot);
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
  const openL = useRef<Group>(null);
  const openR = useRef<Group>(null);
  const curledL = useRef<Group>(null);
  const curledR = useRef<Group>(null);

  // Coarse tiers drop lathe segments: at this size, and this transparent, the
  // silhouette carries everything and the facets never show.
  const segments = tier === 'low' ? 10 : tier === 'medium' ? 14 : 20;

  const body = useMemo(() => buildBody(segments, RIG), [segments]);
  useEffect(() => () => body.dispose(), [body]);

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
   * Three skins, one set of uniforms.
   *
   * The body is not uniform: a plated forearm, the suit under the chest and a
   * fall of hair should not catch light the same way. Each skin therefore owns
   * its own `uPlates` and `uShell`, while spreading the shared uniforms by
   * reference -- the objects inside `uniforms` are the very same holders, so
   * the frame loop still writes the time, the speech level and the presence
   * once and all three follow.
   *
   * Built as objects and handed to each mesh by prop. Declared as JSX and
   * reused, the meshes came out with no material at all and simply were not
   * drawn: the face, which uses ordinary basic materials, rendered on its own
   * in mid-air exactly where the head should have been.
   */
  const skins = useMemo(() => {
    const make = (rings: number, shell: number) =>
      new ShaderMaterial({
        vertexShader: FIGURE_VERT,
        fragmentShader: FIGURE_FRAG,
        uniforms: { ...uniforms, uRings: { value: rings }, uShell: { value: shell } },
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: DoubleSide,
      });
    return {
      /*
       * The body, all of it, on one contour density.
       *
       * There were three skins when the surface was plating, because a plated
       * forearm and the suit beneath the chest are different objects. Contours
       * are the opposite proposition: they describe one continuous form, and
       * the instant the trunk and the arm are cut at different intervals the
       * form comes apart again. So the whole body shares this one.
       */
      body: make(340, 1),
      /*
       * The skull, cut far more coarsely than the rest.
       *
       * Measured: the head lands about forty pixels tall on screen, and at the
       * body's contour spacing that is a dozen rings across a face. No face
       * survives that -- the eyes and the mouth simply became two more stripes.
       * Six or seven rings still read as the same scanned surface and leave the
       * features somewhere to be.
       */
      head: make(130, 1),
      /** Hair is not built and does not get the same treatment. */
      hair: make(150, 0.35),
    };
  }, [uniforms]);
  useEffect(
    () => () => {
      skins.body.dispose();
      skins.head.dispose();
      skins.hair.dispose();
    },
    [skins],
  );
  const material = skins.body;

  /*
   * The plinth it stands on.
   *
   * Every reference for a projected human body has one, and it is doing real
   * work: it says the figure is being projected rather than standing there,
   * and it gives the feet a floor to meet -- which is what the long dissolve
   * up the shins used to stand in for. Rings rather than a solid disc, because
   * a disc under a translucent body reads as a shadow.
   */
  const dais = useMemo(
    () => ({
      line: new MeshBasicMaterial({
        color: PALETTE.signal,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: DoubleSide,
      }),
      fill: new MeshBasicMaterial({
        color: PALETTE.core,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
        side: DoubleSide,
      }),
    }),
    [],
  );
  useEffect(
    () => () => {
      dais.line.dispose();
      dais.fill.dispose();
    },
    [dais],
  );
  const arcA = useRef<Mesh>(null);
  const arcB = useRef<Mesh>(null);

  const place = useMemo(() => new Spring3(HOME, SPRINGS.glide), []);
  const presence = useMemo(() => new Spring(0, SPRINGS.glide), []);
  /** How committed the pose is to indicating something. */
  const showing = useMemo(() => new Spring(0, SPRINGS.glide), []);
  const jaw = useMemo(() => new Spring(0, SPRINGS.flash), []);

  const blink = useRef({ next: 2.4, until: 0 });
  /** Speech envelope recovered from the text, for when there is no audio yet. */
  const spoken = useRef({ length: 0, level: 0 });

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const time = interaction.sceneTime;

    const idle = boot === 'ready' ? IDLE_PRESENCE : 0;
    const wanted =
      Math.max(idle, voice.awakeBlend, attention.weight) * (expandedId ? ASIDE_PRESENCE : 1);
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
    const resting = toTheRight ? shoulderL : shoulderR;
    const restingElbow = toTheRight ? elbowL : elbowR;
    /*
     * Which SIDE of the body each shoulder is on, not which job it is doing.
     * A rest angle swings an arm outward only if its sign follows the shoulder,
     * and conflating the two put the resting arm through the torso whenever the
     * target happened to be on the other side.
     */
    const pointerSide = toTheRight ? 1 : -1;
    const restingSide = -pointerSide;

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

    if (resting.current) {
      /*
       * The resting arm is not dead: while the voice runs it swings a little on
       * the speech envelope. Small beats, shoulder only, so it never competes
       * with the arm doing the pointing.
       */
      const beat = voice.level * 0.16 + noise1(time * 0.6 + 11) * 0.05;
      rest.setFromAxisAngle(FORWARD, restingSide * (0.11 + beat * 0.35));
      resting.current.quaternion.slerp(rest, 1 - Math.exp(-5 * dt));
    }
    if (restingElbow.current) {
      restingElbow.current.rotation.x = damp(
        restingElbow.current.rotation.x,
        -0.36 - voice.level * 0.22,
        5,
        dt,
      );
    }

    /*
     * The hand that points, points with a finger. Swapped rather than animated:
     * both poses are built once, and the arm's own swing covers the change.
     */
    const pointing = show > 0.5;
    if (openL.current) openL.current.visible = pointing && !toTheRight;
    if (curledL.current) curledL.current.visible = !(pointing && !toTheRight);
    if (openR.current) openR.current.visible = pointing && toTheRight;
    if (curledR.current) curledR.current.visible = !(pointing && toTheRight);

    // --- Mouth -----------------------------------------------------------
    /*
     * The mouth follows the speech envelope when there is audio, and the text
     * when there is not.
     *
     * It used to follow the audio alone, on the principle that a mouth moving
     * without sound is miming. That was too strict, and in practice it was
     * simply broken: the reply streams as text for several seconds before the
     * first audio arrives, and when the voice route is unavailable no audio
     * arrives at all -- so the figure delivered whole answers with its mouth
     * shut. Reading the growth of the streamed text gives a real cadence for
     * exactly those moments, and the audio takes over the instant it exists.
     */
    const talking = status === 'speaking' || status === 'streaming';
    const streamed = useAssistantStore.getState().streaming.length;
    const grew = streamed - spoken.current.length;
    spoken.current.length = streamed;
    if (talking && grew > 0) {
      spoken.current.level = Math.min(1, 0.5 + grew * 0.04);
    } else {
      spoken.current.level *= Math.exp(-5.5 * dt);
    }
    const envelope = talking ? Math.max(voice.level, spoken.current.level) : 0;
    jaw.set(clamp01(envelope * 1.2)).update(dt);
    figureReport.mouth = jaw.value;
    if (mouth.current) {
      const open = jaw.value;
      mouth.current.scale.set(1 - open * 0.18, 0.2 + open * 1.5, 1);
      (mouth.current.material as { opacity: number }).opacity = 0.55 + open * 0.45;
    }

    // --- Eyes ------------------------------------------------------------
    /*
     * A blink costs almost nothing and buys the largest share of whatever life
     * this figure has. Random intervals: a regular blink is a metronome, and a
     * metronome reads as a fault.
     */
    if (eyes.current) {
      const b = blink.current;
      if (time > b.next) {
        b.until = time + 0.09;
        b.next = time + 2.2 + Math.random() * 3.6;
      }
      eyes.current.scale.y = time < b.until ? 0.08 : 1;
    }

    /*
     * The plinth. Turning slowly, and brightening with the voice, so it reads
     * as a projector doing work rather than as a decal under the feet.
     */
    dais.line.opacity = here * (0.4 + voice.level * 0.35);
    dais.fill.opacity = here * (0.07 + voice.level * 0.1);
    if (arcA.current) arcA.current.rotation.z = time * 0.22;
    if (arcB.current) arcB.current.rotation.z = -time * 0.15;

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
  });

  const fingers = (places: FingerPlace[]) =>
    places.map((f, i) => (
      <group key={i} position={[f.x, -0.062, 0]} rotation={[f.curl, 0, 0]}>
        <mesh
          material={material}
          geometry={body.finger}
          position={[0, -0.0265 * f.scale, 0]}
          scale={[1, f.scale, 1]}
        />
      </group>
    ));

  const arm = (
    side: -1 | 1,
    shoulder: typeof shoulderL,
    elbow: typeof elbowL,
    open: typeof openL,
    curled: typeof curledL,
  ) => (
    <group ref={shoulder} position={[side * RIG.shoulderX, RIG.shoulderY, 0]}>
      {/*
        Joint balls at the shoulder and the elbow.
        Without them a raised arm reads as a bar floating beside the body
        rather than as a limb attached to it: the profile swings away from the
        torso and nothing bridges the gap it leaves.
      */}
      <mesh material={material} geometry={body.joint} />
      <mesh material={material} geometry={body.upperArm} />
      <group ref={elbow} position={[0, -RIG.upperArm, 0]}>
        <mesh material={material} geometry={body.tinyJoint} />
        <mesh material={material} geometry={body.forearm} />
        <group position={[0, -RIG.forearm, 0]}>
          <mesh material={material} geometry={body.palm} />
          <group ref={open} visible={false}>
            {fingers(HAND_POINTING)}
          </group>
          <group ref={curled}>{fingers(HAND_RELAXED)}</group>
        </group>
      </group>
    </group>
  );

  return (
    <group ref={group} name="assistant-figure" scale={FIGURE_SCALE} visible={false}>
      <group position={[0, RIG.footY - 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <mesh material={dais.fill}>
          <circleGeometry args={[0.36, 48]} />
        </mesh>
        <mesh material={dais.line}>
          <ringGeometry args={[0.44, 0.452, 64]} />
        </mesh>
        {/* Arcs, not rings: a full circle turning looks exactly like a full
            circle standing still. */}
        <mesh ref={arcA} material={dais.line}>
          <ringGeometry args={[0.36, 0.382, 48, 1, 0, 2.3]} />
        </mesh>
        <mesh ref={arcB} material={dais.line}>
          <ringGeometry args={[0.27, 0.284, 48, 1, 0, 1.4]} />
        </mesh>
        <mesh material={dais.line}>
          <ringGeometry args={[0.19, 0.197, 48]} />
        </mesh>
      </group>

      <group ref={root}>
        {/* Legs. Static: this figure stands, it never walks. */}
        {([-1, 1] as const).map((side) => (
          <group key={side} position={[side * RIG.hipX, 0, 0]} rotation={[0.04, 0, side * 0.03]}>
            <mesh material={material} geometry={body.joint} />
            <mesh material={material} geometry={body.thigh} />
            <group position={[0, -RIG.thigh, 0]} rotation={[-0.06, 0, 0]}>
              <mesh material={material} geometry={body.smallJoint} />
              <mesh material={material} geometry={body.shin} />
              <mesh material={material} geometry={body.foot} position={[0, -RIG.shin, 0]} />
            </group>
          </group>
        ))}

        <group ref={chest}>
          <mesh material={skins.body} geometry={body.torso} />

          {arm(-1, shoulderL, elbowL, openL, curledL)}
          {arm(1, shoulderR, elbowR, openR, curledR)}

          <group ref={head} position={[0, RIG.headY, 0]}>
            <mesh material={skins.head} geometry={body.head} />
            {/*
              Hair. It earns its place: in a silhouette this small it is the
              single strongest signal that what you are looking at is a person.
            */}
            <mesh material={skins.hair} geometry={body.hair} />
            <mesh material={skins.hair} geometry={body.fringe} />

            {/*
              Face. Two marks and a mouth, sitting proud of the skull so they
              read through it -- deliberately not a face. Anything more detailed
              at this scale lands in the uncanny valley, and this figure has no
              business being mistaken for a person.
            */}
            {/*
              Pushed a little further out than the skull and drawn at full
              strength: the contour rings cross the head like everything else,
              and at this size a face at the same brightness simply disappears
              into them.
            */}
            <group ref={eyes} position={[0, 0.016, RIG.faceZ + 0.006]}>
              {([-1, 1] as const).map((side) => (
                <mesh key={side} position={[side * 0.036, 0, 0]} rotation={[0, side * -0.24, 0]}>
                  <planeGeometry args={[0.035, 0.016]} />
                  <meshBasicMaterial
                    color={PALETTE.signal}
                    transparent
                    opacity={0.95}
                    depthWrite={false}
                    blending={AdditiveBlending}
                  />
                </mesh>
              ))}
            </group>

            <mesh ref={mouth} position={[0, -0.055, RIG.faceZ]}>
              <planeGeometry args={[0.048, 0.032]} />
              <meshBasicMaterial
                color={PALETTE.lumen}
                transparent
                opacity={0.4}
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
