'use client';

import { memo, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { RoundedBox } from '@react-three/drei';
import { CuboidCollider, RigidBody, type RapierRigidBody } from '@react-three/rapier';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  Euler,
  Group,
  Quaternion,
  Vector3,
  type Mesh,
  type MeshBasicMaterial,
  type MeshPhysicalMaterial,
  type ShaderMaterial,
} from 'three';
import type { ModuleDefinition } from '@/config/modules';
import { PALETTE, SPACE } from '@/config/theme';
import { FRAME_FRAG, FRAME_VERT } from '@/shaders/holoFrame';
import { AngularSpring, Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import {
  idleDrift,
  liveRadius,
  slotAngle,
  slotNormal,
  slotPosition,
  stateAdvance,
  stateEnergy,
  stateLift,
  stateScale,
} from './cardMath';
import { carousel, interaction, pendingImpulses } from '@/stores/runtime';
import { resolveCardState, useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { getCardTexture } from './cardTexture';
import { getGlowTexture } from './glowTexture';
import { bus } from '@/stores/bus';
import { clamp01 } from '@/core/math';
import { useLocaleStore } from '@/i18n';
import { useFeedStore } from '@/modules/store';
import { deriveFace } from '@/modules/faces';
import type { CardState } from '@/core/types';

interface HoloCardProps {
  module: ModuleDefinition;
  index: number;
}

/** Scratch vectors — module scope, reused by every card, never allocated in a frame. */
const sPos: [number, number, number] = [0, 0, 0];
const sNormal: [number, number, number] = [0, 0, 0];
const sDrift: [number, number, number, number, number] = [0, 0, 0, 0, 0];
const vTmp = new Vector3();
const vTarget = new Vector3();
const qTmp = new Quaternion();
const eTmp = new Euler();

/** Speed below which a free-flying card is considered home. */
const SETTLE_SPEED = 0.55;
const SETTLE_DISTANCE = 0.42;

export const HoloCard = memo(function HoloCard({ module, index }: HoloCardProps) {
  const body = useRef<RapierRigidBody>(null);
  const visual = useRef<Group>(null);
  const frameMat = useRef<ShaderMaterial>(null);
  const glowMesh = useRef<Mesh>(null);
  const faceMat = useRef<MeshBasicMaterial>(null);
  const glassMat = useRef<MeshPhysicalMaterial>(null);

  const profile = useSystemStore((s) => s.profile);
  /** Authoritative: a card is free exactly while the store says it is flying. */
  const free = useCarouselStore((s) => s.freeIds.includes(module.id));

  const locale = useLocaleStore((s) => s.locale);

  /*
   * The card face is now a readout, not a print. It repaints whenever the
   * module's live numbers move - roughly once a minute for markets, once every
   * five for weather - and the painter caches by value, so a card whose data
   * has not changed costs nothing.
   */
  const feed = useFeedStore((s) => s.feeds[module.id]);
  const face = useMemo(() => deriveFace(module, feed), [module, feed]);
  const texture = useMemo(
    () => getCardTexture(module, index, locale, face),
    [module, index, locale, face],
  );
  const glowTex = useMemo(() => getGlowTexture(), []);

  const warn = face.status === 'attention';

  const frameUniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: { x: SPACE.cardWidth, y: SPACE.cardHeight } },
      uRadius: { value: SPACE.cardRadius },
      uColor: { value: new Color(PALETTE.signal) },
      uAccent: { value: new Color(PALETTE.ember) },
      uEnergy: { value: 0.13 },
      uSelect: { value: 0 },
      uWarn: { value: warn ? 1 : 0 },
      uFreeze: { value: 0 },
      uAspect: { value: SPACE.cardWidth / SPACE.cardHeight },
      uRipple: { value: -1 },
      uRippleAt: { value: { x: 0.5, y: 0.5 } },
    }),
    [warn],
  );

  /** Seconds elapsed on the current ripple, or -1 when idle. */
  const ripple = useRef({ at: -1, x: 0.5, y: 0.5 });

  /** Strike the glass. Called on every state change and on contact. */
  const strike = (x = 0.5, y = 0.5) => {
    ripple.current = { at: 0, x, y };
  };

  /**
   * The back of a card carries the same frame at a fraction of the energy.
   * Without this the reverse of a far card is as bright as the front of a near
   * one, and the ring loses its front-to-back reading entirely.
   */
  const backUniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: { x: SPACE.cardWidth, y: SPACE.cardHeight } },
      uRadius: { value: SPACE.cardRadius },
      uColor: { value: new Color(PALETTE.core) },
      uAccent: { value: new Color(PALETTE.ember) },
      uEnergy: { value: 0.05 },
      uSelect: { value: 0 },
      uWarn: { value: warn ? 1 : 0 },
      uFreeze: { value: 0 },
      uAspect: { value: SPACE.cardWidth / SPACE.cardHeight },
    }),
    [warn],
  );

  /**
   * One spring set per card, created once. These ARE the card — every visible
   * difference between states is these springs converging on different targets
   * with different configs, never a keyframed transition.
   */
  const motion = useMemo(() => {
    const angle = slotAngle(index, carousel.angle);
    slotPosition(angle, sPos);
    return {
      position: new Spring3([sPos[0], sPos[1], sPos[2]], SPRINGS.crisp),
      yaw: new AngularSpring(angle, SPRINGS.crisp),
      tiltX: new Spring(0, SPRINGS.crisp),
      tiltZ: new Spring(0, SPRINGS.crisp),
      scale: new Spring(1, SPRINGS.elastic),
      energy: new Spring(0.13, SPRINGS.flash),
      opacity: new Spring(1, SPRINGS.crisp),
      /** Remembers the previous state so transitions can fire once. */
      lastState: 'idle' as CardState,
      /** Set when this card was thrown; suppresses slot tracking until settled. */
      flying: false,
      grabWorld: new Vector3(),
    };
  }, [index]);

  const wasFree = useRef(false);

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const store = useCarouselStore.getState();
    const state = resolveCardState(module.id, index, store);
    const rb = body.current;

    const angle = slotAngle(index, carousel.angle);
    // The ring breathes with the two-handed spread dial.
    slotPosition(angle, sPos, liveRadius(interaction.spread));
    slotNormal(angle, sNormal);

    // --- state transitions ------------------------------------------------
    if (state !== motion.lastState) {
      // The spring CONFIG changes with state, which is why each state has a
      // recognisably different motion signature rather than a different curve.
      motion.position.configure(
        state === 'dragging' ? SPRINGS.lag : state === 'expanded' ? SPRINGS.bouncy : SPRINGS.crisp,
      );
      motion.scale.configure(state === 'expanded' ? SPRINGS.bouncy : SPRINGS.elastic);
      motion.yaw.configure(state === "dragging" ? SPRINGS.lag : SPRINGS.crisp);
      bus.emit('card:state', { id: module.id, state });
      // Every state change is a touch; the glass should acknowledge it.
      strike();
      motion.lastState = state;
    }

    // --- free flight ------------------------------------------------------
    if (free && rb) {
      if (!wasFree.current) {
        wasFree.current = true;
        const impulse = pendingImpulses.get(module.id);
        if (impulse) {
          pendingImpulses.delete(module.id);
          rb.setLinvel({ x: impulse.lin[0], y: impulse.lin[1], z: impulse.lin[2] }, true);
          rb.setAngvel({ x: impulse.ang[0], y: impulse.ang[1], z: impulse.ang[2] }, true);
        }
      }

      const t = rb.translation();
      // Spring-shaped attractor: the ring never lets a card leave for good, but
      // it pulls with force, not with a lerp, so the return has real momentum.
      vTarget.set(sPos[0], sPos[1], sPos[2]);
      vTmp.set(t.x, t.y, t.z);
      const toSlot = vTarget.sub(vTmp);
      const distance = toSlot.length();
      const pull = Math.min(distance, 3) * 1.5;
      toSlot.normalize().multiplyScalar(pull * dt * 60 * 0.02);
      rb.applyImpulse({ x: toSlot.x, y: toSlot.y, z: toSlot.z }, true);

      const lv = rb.linvel();
      const speed = Math.hypot(lv.x, lv.y, lv.z);
      if (distance < SETTLE_DISTANCE && speed < SETTLE_SPEED) {
        const r = rb.rotation();
        eTmp.setFromQuaternion(qTmp.set(r.x, r.y, r.z, r.w));
        motion.position.jump(t.x, t.y, t.z);
        motion.yaw.jump(eTmp.y);
        motion.tiltX.jump(eTmp.x);
        motion.tiltZ.jump(eTmp.z);
        wasFree.current = false;
        useCarouselStore.getState().settle(module.id);
        bus.emit('card:settled', { id: module.id });
      }

      // The visual layer still animates while the body flies.
      motion.energy.set(0.62);
      motion.energy.update(dt);
      motion.scale.update(dt);
      applyVisuals(dt);
      return;
    }

    if (wasFree.current) wasFree.current = false;

    // --- targets ----------------------------------------------------------
    idleDrift(module.seed, interaction.sceneTime, sDrift);
    // Freezing does not zero the drift, it thickens the medium.
    const ds = 1 - interaction.freezeBlend * 0.9;

    // When another card is expanded, everything else politely gets out of the way.
    const suppressed = store.expandedId !== null && store.expandedId !== module.id;
    const front = (Math.cos(angle) + 1) * 0.5;

    let tx: number;
    let ty: number;
    let tz: number;
    let tYaw: number;
    let tTiltX = sDrift[3] * ds;
    let tTiltZ = sDrift[4] * ds;

    if (state === 'expanded') {
      tx = 0;
      ty = SPACE.orbitHeight + 0.18 + sDrift[1] * ds * 0.25;
      tz = SPACE.orbitRadius + SPACE.expandAdvance;
      tYaw = 0;
      tTiltX *= 0.2;
      tTiltZ *= 0.2;
    } else if (state === 'dragging') {
      tx = interaction.aimX + interaction.grabOffset[0];
      ty = interaction.aimY + interaction.grabOffset[1];
      tz = interaction.aimZ + interaction.grabOffset[2];
      // Face outward from the ring centre — at the front of the ring that is
      // the camera, and it stays stable if the card is dragged round the side.
      tYaw = Math.atan2(tx, tz);
      // Bank into the direction of travel. Reading the spring's own velocity
      // for this is what makes a dragged card feel like it has mass.
      tTiltZ = -motion.position.x.velocity * 0.09;
      tTiltX = motion.position.y.velocity * 0.05;
    } else {
      const advance = stateAdvance(state) * (suppressed ? 0.25 : 1);
      tx = sPos[0] + sNormal[0] * advance + sDrift[0] * ds;
      ty = sPos[1] + stateLift(state) + sDrift[1] * ds;
      tz = sPos[2] + sNormal[2] * advance + sDrift[2] * ds;
      tYaw = angle;
    }

    motion.position.set(tx, ty, tz);
    motion.yaw.set(tYaw);
    motion.tiltX.set(tTiltX);
    motion.tiltZ.set(tTiltZ);
    motion.scale.set(stateScale(state) * (suppressed ? 0.86 : 1));
    motion.energy.set(
      suppressed ? 0.06 : stateEnergy(state) * (0.55 + front * 0.45),
    );
    motion.opacity.set(suppressed ? 0.34 : 0.42 + front * 0.58);

    motion.position.update(dt);
    motion.yaw.update(dt);
    motion.tiltX.update(dt);
    motion.tiltZ.update(dt);
    motion.scale.update(dt);
    motion.energy.update(dt);
    motion.opacity.update(dt);

    if (rb) {
      rb.setNextKinematicTranslation({
        x: motion.position.x.value,
        y: motion.position.y.value,
        z: motion.position.z.value,
      });
      eTmp.set(motion.tiltX.value, motion.yaw.value, motion.tiltZ.value, 'YXZ');
      qTmp.setFromEuler(eTmp);
      rb.setNextKinematicRotation({ x: qTmp.x, y: qTmp.y, z: qTmp.z, w: qTmp.w });
    }

    applyVisuals(dt);
  });

  /** Everything that lives on the visual group rather than the rigid body. */
  function applyVisuals(dt: number) {
    const energy = motion.energy.value;

    if (visual.current) {
      const s = motion.scale.value;
      visual.current.scale.set(s, s, s);
    }

    // Advance the ripple clock and hand it to both faces.
    if (ripple.current.at >= 0) {
      ripple.current.at += dt;
      if (ripple.current.at > 1.2) ripple.current.at = -1;
    }

    if (frameMat.current) {
      const u = frameMat.current.uniforms;
      u.uRipple.value = ripple.current.at;
      (u.uRippleAt.value as { x: number; y: number }).x = ripple.current.x;
      (u.uRippleAt.value as { x: number; y: number }).y = ripple.current.y;
      frameUniforms.uTime.value = interaction.sceneTime;
      frameUniforms.uEnergy.value = energy;
      frameUniforms.uFreeze.value = interaction.freezeBlend;
      // uSelect biases the pulse phase so selected cards visibly lead.
      frameUniforms.uSelect.value = clamp01((energy - 0.5) * 2);

      backUniforms.uTime.value = interaction.sceneTime;
      backUniforms.uEnergy.value = energy * 0.3;
      backUniforms.uFreeze.value = interaction.freezeBlend;
    }

    if (faceMat.current) faceMat.current.opacity = motion.opacity.value;
    if (glassMat.current) {
      // Glass gets fractionally clearer and more emissive as it wakes up.
      glassMat.current.emissiveIntensity = 0.12 + energy * 0.75;
      glassMat.current.roughness = 0.24 - energy * 0.1;
    }

    if (glowMesh.current) {
      const mat = glowMesh.current.material as { opacity: number };
      mat.opacity = 0.06 + energy * 0.42;
      const g = 1 + energy * 0.28;
      glowMesh.current.scale.set(g, g, 1);
    }
    void dt;
  }

  // --- pointer fallback ---------------------------------------------------
  // Hands are the primary input; these handlers exist so the OS is still
  // fully operable with a mouse, on a machine with no camera, or when the
  // user simply has not granted permission.
  const cards = useCarouselStore;

  const onOver = (event?: { uv?: { x: number; y: number } }) => {
    if (cards.getState().expandedId) return;
    // Ripple from where the pointer actually touched, when we know it.
    if (event?.uv) strike(event.uv.x, event.uv.y);
    cards.getState().setHovered(module.id);
  };
  const onOut = () => {
    if (cards.getState().hoveredId === module.id) cards.getState().setHovered(null);
  };
  const onDown = () => {
    const s = cards.getState();
    if (s.expandedId && s.expandedId !== module.id) return;
    s.beginDrag(module.id);
  };
  const onUp = () => {
    const s = cards.getState();
    if (s.draggingId === module.id) s.endDrag(module.id, false);
  };
  const onDoubleClick = () => {
    const s = cards.getState();
    if (s.expandedId === module.id) s.collapse();
    else s.expand(module.id);
  };

  const initial = useMemo<[number, number, number]>(() => {
    const a = slotAngle(index, 0);
    slotPosition(a, sPos);
    return [sPos[0], sPos[1], sPos[2]];
  }, [index]);

  const half: [number, number, number] = [
    SPACE.cardWidth / 2,
    SPACE.cardHeight / 2,
    SPACE.cardDepth / 2,
  ];

  return (
    <RigidBody
      ref={body}
      type={free ? 'dynamic' : 'kinematicPosition'}
      colliders={false}
      position={initial}
      /* Near-zero gravity: a dropped card sinks, it does not fall. */
      gravityScale={free ? 0.35 : 0}
      linearDamping={1.15}
      angularDamping={2.1}
      canSleep={false}
      ccd={free}
    >
      <CuboidCollider args={half} />

      <group ref={visual}>
        {/* Volumetric bloom source behind the slab. */}
        <mesh ref={glowMesh} position={[0, 0, -0.07]}>
          <planeGeometry args={[SPACE.cardWidth * 2.6, SPACE.cardHeight * 2.1]} />
          <meshBasicMaterial
            map={glowTex}
            color={warn ? PALETTE.ember : PALETTE.signal}
            transparent
            opacity={0.08}
            blending={AdditiveBlending}
            depthWrite={false}
            toneMapped={false}
            side={DoubleSide}
          />
        </mesh>

        {/* The glass slab. Real refraction when the tier allows it. */}
        <RoundedBox
          args={[SPACE.cardWidth, SPACE.cardHeight, SPACE.cardDepth]}
          radius={SPACE.cardRadius}
          smoothness={4}
          onPointerOver={onOver}
          onPointerOut={onOut}
          onPointerDown={onDown}
          onPointerUp={onUp}
          onDoubleClick={onDoubleClick}
        >
          <meshPhysicalMaterial
            ref={glassMat}
            color={PALETTE.slate}
            emissive={warn ? PALETTE.ember : PALETTE.core}
            emissiveIntensity={0.12}
            metalness={0.05}
            roughness={0.24}
            /* Built-in transmission shares ONE render pass across every card;
               drei's transmission material would cost one pass per card. */
            transmission={profile.transmission ? 0.72 : 0}
            thickness={0.5}
            ior={1.34}
            clearcoat={1}
            clearcoatRoughness={0.22}
            envMapIntensity={profile.liveReflections ? 1.6 : 1.1}
            transparent
            opacity={profile.transmission ? 1 : 0.72}
          />
        </RoundedBox>

        {/* Painted face. */}
        <mesh position={[0, 0, SPACE.cardDepth / 2 + 0.003]}>
          <planeGeometry args={[SPACE.cardWidth * 0.93, SPACE.cardHeight * 0.94]} />
          <meshBasicMaterial
            ref={faceMat}
            map={texture}
            transparent
            opacity={1}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>

        {/* Animated border, front and back so the ring reads from any angle. */}
        <mesh position={[0, 0, SPACE.cardDepth / 2 + 0.006]}>
          <planeGeometry args={[SPACE.cardWidth * 1.04, SPACE.cardHeight * 1.03]} />
          <shaderMaterial
            ref={frameMat}
            vertexShader={FRAME_VERT}
            fragmentShader={FRAME_FRAG}
            uniforms={frameUniforms}
            transparent
            depthWrite={false}
            blending={AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
        <mesh position={[0, 0, -SPACE.cardDepth / 2 - 0.006]} rotation={[0, Math.PI, 0]}>
          <planeGeometry args={[SPACE.cardWidth * 1.04, SPACE.cardHeight * 1.03]} />
          <shaderMaterial
            vertexShader={FRAME_VERT}
            fragmentShader={FRAME_FRAG}
            uniforms={backUniforms}
            transparent
            depthWrite={false}
            blending={AdditiveBlending}
            toneMapped={false}
          />
        </mesh>
      </group>
    </RigidBody>
  );
});
