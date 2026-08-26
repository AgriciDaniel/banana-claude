'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Quaternion,
  SRGBColorSpace,
  TextureLoader,
  Vector3,
  type Group,
  type Mesh,
  type Texture,
} from 'three';
import { makeFace, makePlate, setFace, setFaceCrop, setGlow } from './plating';
import { PALETTE } from '@/config/theme';
import { attention, interaction, voice } from '@/stores/runtime';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { clamp01, damp, noise1 } from '@/core/math';
import { FORWARD, HEAD_CONE, REST_DIR, RIG, aimAt, clampToCone } from './rig';
import {
  HAND_POINTING,
  HAND_RELAXED,
  buildBody,
  buildMechanism,
  type FingerPlace,
} from './body';
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
 * can see it is not a presence. So it stands there once the room has booted,
 * and its lights come up when it is spoken to or has something to show.
 *
 * High, now that presence means opacity on a solid body: at a half it was a
 * ghost of a robot, which is neither one thing nor the other.
 */
const IDLE_PRESENCE = 0.88;

/**
 * The generated face.
 *
 * Made once by `npm run make:face` and cached to disk. The model answers in
 * whatever format it likes, so both names are tried; absent either, the figure
 * wears the plain visor and nothing breaks.
 */
const FACE_URLS = ['/avatar/face.jpg', '/avatar/face.png'];
/**
 * Sized to the skull it hangs on: the generated frame runs forehead to chin,
 * and the head profile spans -0.1 to +0.104. Square, because the crop is.
 */
const FACE_W = 0.203;
const FACE_H = 0.204;

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

  /* The frame under the plates: core, cables, discs, finger bones. */
  const mech = useMemo(() => buildMechanism(segments, RIG), [segments]);
  useEffect(() => () => mech.dispose(), [mech]);

  /*
   * The shells.
   *
   * Not one material but four, because a machine is not uniformly divided: a
   * forearm is broken into more plates than a chest, and a helmet into none at
   * all. They differ only in how often the shell is cut and what colour sits in
   * the cut -- everything about the way light lands on them is stock, which is
   * the whole reason these are patched standard materials and not a shader of
   * my own. See plating.ts.
   */
  const skins = useMemo(
    () => ({
      /** Limbs, joints, hands, feet: the most divided parts. */
      shell: makePlate({ plates: 5 }),
      /** The trunk. Fewer, larger plates, as a chest piece would be. */
      torso: makePlate({ plates: 4 }),
      /** The helmet is unbroken. A seam across a face is a crack in it. */
      helmet: makePlate({ plates: 0, roughness: 0.24, metalness: 0.45 }),
      /*
       * Copper, for the parts that are not shell: the neck run and the joints
       * behind the plates. Every reference sets a second, warmer metal against
       * the white, and it is what stops the figure reading as one moulded
       * object. Hair used to be here -- it was the strongest way to say
       * "person" in a silhouette, and it stopped making sense the moment the
       * head became a helmet.
       */
      copper: makePlate({ plates: 3, colour: '#C98A5B', metalness: 0.85, roughness: 0.42, seam: '#FFB27A' }),
      /*
       * The frame the shell is bolted to: dark, matte, and visible in every
       * gap the plates leave -- the neck, the flanks, the backs of the joints.
       * That gap is the detail. Seams drawn on an unbroken surface can only
       * ever suggest it.
       */
      carbon: makePlate({ plates: 7, colour: '#1B2028', metalness: 0.65, roughness: 0.55 }),
      /** The band the optics sit in: glossy, near-black, no seams. */
      visor: makePlate({ plates: 0, colour: '#0A0D12', metalness: 0.3, roughness: 0.12 }),
      /*
       * Everything that lights up: eyes, temple rings, the vocal vent. One
       * material, so the whole face brightens and dims together -- and it is
       * emissive rather than plated, because a light is not a surface with a
       * seam in it.
       */
      optic: new MeshStandardMaterial({
        color: new Color('#08131A'),
        emissive: new Color(PALETTE.signal),
        emissiveIntensity: 3.2,
        roughness: 0.3,
        metalness: 0,
        transparent: true,
      }),
    }),
    [],
  );
  useEffect(
    () => () => {
      Object.values(skins).forEach((m) => m.dispose());
    },
    [skins],
  );
  const material = skins.shell;

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

  /*
   * Loading it, and finding out how it was framed.
   *
   * The crop comes off the loaded image rather than from an assumption: the
   * model answers square when asked and landscape when it feels like it, and a
   * face stretched across a square plane is the loudest way to discover which
   * happened.
   */
  const [face, setFaceTexture] = useState<Texture | null>(null);
  useEffect(() => {
    let alive = true;
    let loaded: Texture | null = null;
    const loader = new TextureLoader();
    const attempt = (index: number): void => {
      if (index >= FACE_URLS.length) return;
      loader.load(
        FACE_URLS[index]!,
        (texture) => {
          if (!alive) {
            texture.dispose();
            return;
          }
          texture.colorSpace = SRGBColorSpace;
          loaded = texture;
          setFaceTexture(texture);
        },
        undefined,
        () => attempt(index + 1),
      );
    };
    attempt(0);
    return () => {
      alive = false;
      loaded?.dispose();
    };
  }, []);

  const faceSkin = useMemo(() => (face ? makeFace(face) : null), [face]);
  useEffect(() => {
    if (!faceSkin || !face) return undefined;
    const image = face.image as { width?: number; height?: number } | undefined;
    if (image?.width && image.height) setFaceCrop(faceSkin, image.width / image.height);
    return () => faceSkin.dispose();
  }, [faceSkin, face]);

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

    /*
     * Presence is now opacity and seam brightness rather than a shader term.
     * A plated body cannot fade by being drawn more faintly on top of the
     * room -- it has to actually go translucent, and its lights have to go
     * out with it.
     */
    /*
     * The seams have to fight a lit white shell now, not a dark room. On the
     * hologram a value near one was plenty; against ceramic under a key light
     * the same value simply vanished.
     */
    const glow = here * (3.2 + voice.level * 3.4);
    for (const skin of Object.values(skins)) {
      skin.opacity = here;
      setGlow(skin, glow);
    }

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
      /*
       * The vent opens and brightens together. Scale alone reads as a shutter;
       * light alone reads as a lamp being turned up. Both at once reads as a
       * thing speaking.
       */
      const open = jaw.value;
      mouth.current.scale.set(1 - open * 0.12, 0.35 + open * 1.9, 1);
    }
    skins.optic.emissiveIntensity = here * (3.4 + jaw.value * 4.5);
    /* The painted face does its own talking: the rows around its lips stretch. */
    if (faceSkin) setFace(faceSkin, jaw.value, here);

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
     * The generated face does not blink. Blinking means briefly hiding the
     * eyes, and on an additively blended image there is nothing to hide them
     * WITH -- you cannot draw darkness. Two abstract marks could be scaled to
     * nothing; a painted face cannot, so it simply looks at you.
     */

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

  /*
   * Fingers with bones in them.
   *
   * One capsule per finger was a peg. A finger is a knuckle and two segments
   * that fold at different rates, and it is the SECOND fold that reads: a
   * pointing hand is legible because three of its fingers are curled and one
   * is not, which needs joints to be true.
   */
  const fingers = (places: FingerPlace[]) =>
    places.map((f, i) => (
      <group key={i} position={[f.x, -0.062, 0]} rotation={[f.curl, 0, 0]}>
        <mesh material={skins.copper} geometry={mech.knuckle} />
        <mesh
          material={material}
          geometry={mech.phalanx}
          position={[0, -0.0155 * f.scale, 0]}
          scale={[1, f.scale, 1]}
        />
        <group position={[0, -0.031 * f.scale, 0]} rotation={[f.curl * 0.6, 0, 0]}>
          <mesh
            material={material}
            geometry={mech.phalanx}
            position={[0, -0.013 * f.scale, 0]}
            scale={[0.82, f.scale * 0.82, 0.82]}
          />
        </group>
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
      <mesh material={skins.copper} geometry={body.joint} />
      {/* The deltoid cap, with its ring lit. */}
      <group position={[side * 0.012, 0.004, 0]} rotation={[0, 0, Math.PI / 2]}>
        <mesh material={skins.shell} geometry={mech.disc} scale={0.86} />
        <mesh
          material={skins.optic}
          geometry={mech.discRing}
          position={[0, side * 0.011, 0]}
          rotation={[Math.PI / 2, 0, 0]}
          scale={0.8}
        />
      </group>
      <mesh material={material} geometry={body.upperArm} />
      {/* A light let into the forearm plate, as the references carry. */}
      <mesh
        material={skins.optic}
        geometry={mech.slot}
        position={[side * 0.022, -RIG.upperArm * 0.55, 0.026]}
        rotation={[0.35, 0, 0]}
        scale={[0.8, 0.9, 1]}
      />
      <group ref={elbow} position={[0, -RIG.upperArm, 0]}>
        <mesh material={skins.copper} geometry={body.tinyJoint} />
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

      {/*
        Its own key light.
        The room is lit almost entirely blue, and a white ceramic shell under a
        blue key is a grey shell -- which is exactly how the first plated
        version came out. A presenter gets lit like one: a small warm-neutral
        source in front and above, close enough to fall off before it reaches
        anything else in the scene.
      */}
      <pointLight position={[0.48, 1.02, 0.95]} intensity={2.6} distance={3.0} decay={2} color="#FFF4E6" />
      {/* And a cool fill from the other side, so the shadow side is not dead. */}
      <pointLight position={[-0.85, 0.5, 0.7]} intensity={0.75} distance={2.4} decay={2} color="#BFE4FF" />

      <group ref={root}>
        {/* Legs. Static: this figure stands, it never walks. */}
        {([-1, 1] as const).map((side) => (
          <group key={side} position={[side * RIG.hipX, 0, 0]} rotation={[0.04, 0, side * 0.03]}>
            <mesh material={skins.copper} geometry={body.joint} />
            <mesh material={material} geometry={body.thigh} />
            <group position={[0, -RIG.thigh, 0]} rotation={[-0.06, 0, 0]}>
              <mesh material={skins.copper} geometry={body.smallJoint} />
              <mesh material={material} geometry={body.shin} />
              <mesh material={material} geometry={body.foot} position={[0, -RIG.shin, 0]} />
            </group>
          </group>
        ))}

        <group ref={chest}>
          {/*
            The trunk: a dark core with white shell laid over it, front and
            back, leaving a gap down each flank. Three bands across the
            abdomen, because a single piece there cannot bend and reads as a
            barrel.
          */}
          <mesh material={skins.carbon} geometry={mech.core} />
          <mesh material={skins.torso} geometry={mech.chestPlate} />
          <mesh material={skins.torso} geometry={mech.backPlate} />
          {[0.022, 0.068, 0.114, 0.16].map((y) => (
            <mesh key={y} material={skins.torso} geometry={mech.abBand} position={[0, y, 0]} />
          ))}

          {/* Light let into the chest plate, and the spine behind it. */}
          {[-1, 1].map((side) => (
            <mesh
              key={side}
              material={skins.optic}
              geometry={mech.slot}
              position={[side * 0.052, 0.285, 0.115]}
              rotation={[0, side * 0.42, 0]}
            />
          ))}
          {[0.09, 0.14, 0.19].map((y) => (
            <mesh
              key={y}
              material={skins.optic}
              geometry={mech.slot}
              position={[0, y, -0.098]}
              rotation={[0, Math.PI, 0]}
              scale={[0.7, 0.8, 1]}
            />
          ))}

          {/*
            Neck cables. A bundle, not a cable: the references run four or five
            from the base of the skull down behind the collar, and one on its
            own reads as a mistake rather than as an anatomy.
          */}
          {[
            { x: 1, s: 1, copper: false },
            { x: -1, s: 1, copper: false },
            { x: 1, s: 0.82, copper: true },
            { x: -1, s: 0.82, copper: true },
          ].map((c, i) => (
            <mesh
              key={i}
              material={c.copper ? skins.copper : skins.carbon}
              geometry={mech.cable}
              scale={[c.x * c.s, 1, c.s]}
            />
          ))}

          {/* The collar they gather into. */}
          <mesh material={skins.copper} geometry={mech.collar} position={[0, RIG.neckY + 0.03, 0]} />

          {/* Hip units. Every reference puts a disc here, and it is what stops
              the pelvis reading as the bottom of a tube. */}
          {([-1, 1] as const).map((side) => (
            <group key={side} position={[side * 0.096, 0.01, 0.008]} rotation={[0, 0, Math.PI / 2]}>
              <mesh material={skins.shell} geometry={mech.disc} />
              <mesh
                material={skins.optic}
                geometry={mech.discRing}
                position={[0, side * 0.011, 0]}
                rotation={[Math.PI / 2, 0, 0]}
              />
            </group>
          ))}

          {arm(-1, shoulderL, elbowL, openL, curledL)}
          {arm(1, shoulderR, elbowR, openR, curledR)}

          <group ref={head} position={[0, RIG.headY, 0]}>
            <mesh material={skins.helmet} geometry={body.head} />

            {/*
              Face. Two marks and a mouth, sitting proud of the skull so they
              read through it -- deliberately not a face. Anything more detailed
              at this scale lands in the uncanny valley, and this figure has no
              business being mistaken for a person.
            */}
            {faceSkin ? (
              /*
               * The generated face, lying flat against the front of the skull.
               *
               * Flat rather than wrapped: the head turns about fifty degrees at
               * most, and a plane foreshortens across that range much the way a
               * face does. Wrapping it onto a sphere sector would follow the
               * curvature and cost the features their proportions, which at
               * this size is the whole of the face.
               */
              <mesh material={faceSkin} position={[0, 0.002, RIG.faceZ + 0.003]}>
                <planeGeometry args={[FACE_W, FACE_H]} />
              </mesh>
            ) : (
              /*
               * No generated face: a visor and two optics. At forty pixels a
               * face is two lights and a line, and that is a perfectly good
               * face -- it simply is not the one the references carry.
               */
              <>
                <mesh material={skins.visor} position={[0, 0.015, RIG.faceZ - 0.012]}>
                  <boxGeometry args={[0.126, 0.036, 0.05]} />
                </mesh>
                <group ref={eyes} position={[0, 0.017, RIG.faceZ + 0.008]}>
                  {([-1, 1] as const).map((side) => (
                    <mesh key={side} material={skins.optic} position={[side * 0.031, 0, 0]}>
                      <capsuleGeometry args={[0.0072, 0.019, 2, 8]} />
                    </mesh>
                  ))}
                </group>
              </>
            )}

            {/* Temple units. Every reference has them, and they are what stops
                a smooth helmet reading as an egg. */}
            {([-1, 1] as const).map((side) => (
              <group key={side} position={[side * 0.079, 0.005, 0.006]} rotation={[0, 0, side * Math.PI / 2]}>
                <mesh material={skins.shell}>
                  <cylinderGeometry args={[0.031, 0.031, 0.016, 16]} />
                </mesh>
                <mesh material={skins.optic} position={[0, side * 0.009, 0]}>
                  <cylinderGeometry args={[0.014, 0.014, 0.003, 14]} />
                </mesh>
              </group>
            ))}

            {/*
              The vocal vent. It used to BE the mouth; with a painted face that
              opens on its own it becomes what the references actually show --
              a lit bar under the jaw that answers the voice. Two signals for
              one thing, which is what makes speech read at this size.
            */}
            <mesh
              ref={mouth}
              material={skins.optic}
              position={[0, faceSkin ? -0.096 : -0.052, RIG.faceZ - (faceSkin ? 0.03 : 0.008)]}
            >
              <boxGeometry args={[0.044, 0.012, 0.018]} />
            </mesh>
          </group>
        </group>
      </group>
    </group>
  );
}
