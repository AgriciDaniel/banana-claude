'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import {
  AdditiveBlending,
  Color,
  DoubleSide,
  LinearFilter,
  SRGBColorSpace,
  TextureLoader,
  VideoTexture,
  type Group,
  type Mesh,
  type ShaderMaterial,
  type Texture,
} from 'three';
import { FRAME_FRAG, FRAME_VERT } from '@/shaders/holoFrame';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';
import { useMediaStore } from '@/stores/useMediaStore';
import { getChartTexture, REVEAL_STEPS } from './chartTexture';
import { getCloseTexture } from './closeTexture';
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import type { MediaItem } from '@/media/types';
import { ShapeView } from './ShapeView';
import { getAudio } from '@/audio/AudioEngine';

/**
 * One piece of content, framed and floating.
 *
 * Deliberately built from the same parts as a module card — the holographic
 * border shader, the spring vocabulary, the glass slab — so an image the
 * assistant conjures belongs to the room rather than looking like a browser
 * window someone left open in it.
 *
 * Textures are loaded imperatively rather than through drei's `useTexture`,
 * which suspends: a slow image would otherwise blank the entire scene, ring
 * and all, until it finished downloading.
 */

const WIDTH = 2.5;
/**
 * Nothing hangs taller than this, whatever its proportions. Set by the top of
 * the viewport rather than by taste: a portrait photograph any taller pushes
 * its own corner -- and the dismiss cross in it -- off the top of the screen.
 */
const MAX_HEIGHT = 1.8;
/** Depth offsets for the stack behind the focused frame. */
const STEP = 0.34;
/** How far a pair shrinks to make room for each other. */
const PAIR_SCALE = 0.82;

/** A chart is painted at 1024x640, so it always hangs in that proportion. */
const CHART_ASPECT = 1024 / 640;

export function MediaFrame({
  item,
  index,
  retiring = false,
  pairSide = null,
}: {
  item: MediaItem;
  index: number;
  /** Belongs to a finished topic: shrink away rather than linger behind. */
  retiring?: boolean;
  /**
   * Half of a two-piece answer -- a photograph and the factsheet that explains
   * it. Set, the frame takes its side rather than its place in the stack.
   */
  pairSide?: 'left' | 'right' | null;
}) {
  const group = useRef<Group>(null);
  const plane = useRef<Mesh>(null);
  const border = useRef<ShaderMaterial>(null);
  const [texture, setTexture] = useState<Texture | null>(null);
  const [failed, setFailed] = useState(false);
  const setAspect = useMediaStore((s) => s.setAspect);
  const dismiss = useMediaStore((s) => s.dismiss);
  const currentTopic = useMediaStore((s) => s.topic);
  const [revealStep, setRevealStep] = useState(0);

  /*
   * Belongs to a question that has been superseded. It is not gone -- a
   * follow-up that draws nothing should still leave the user looking at what
   * they were discussing -- but it stops holding the centre, so the room reads
   * as being about the current question.
   */
  const stale = !retiring && item.topic !== currentTopic;
  const focused = index === 0 && !retiring && !stale;

  /*
   * Charts draw themselves, so they need no loader -- but they do need to grow
   * in, because a bar chart that simply appears reads as a screenshot. The
   * spring below advances a step counter and the painter is asked for that
   * step, which keeps repaints to two dozen for the whole animation instead of
   * one per frame.
   */
  const reveal = useMemo(() => new Spring(0, SPRINGS.glide), []);
  const chartTexture = useMemo(
    () => (item.chart ? getChartTexture(item.chart, revealStep) : null),
    [item.chart, revealStep],
  );

  // --- texture ------------------------------------------------------------
  useEffect(() => {
    if (item.kind === 'shape' || item.kind === 'chart' || !item.src) return;
    let disposed = false;

    if (item.kind === 'video') {
      const video = document.createElement('video');
      video.src = item.src;
      video.crossOrigin = 'anonymous';
      video.loop = true;
      video.muted = true;
      video.playsInline = true;
      const onReady = () => {
        if (disposed) return;
        const tex = new VideoTexture(video);
        tex.colorSpace = SRGBColorSpace;
        tex.minFilter = LinearFilter;
        setTexture(tex);
        if (video.videoWidth) setAspect(item.id, video.videoWidth / video.videoHeight);
        void video.play().catch(() => setFailed(true));
      };
      video.addEventListener('loadeddata', onReady);
      video.addEventListener('error', () => !disposed && setFailed(true));
      return () => {
        disposed = true;
        video.removeEventListener('loadeddata', onReady);
        video.pause();
        video.src = '';
      };
    }

    new TextureLoader().load(
      item.src,
      (tex) => {
        if (disposed) {
          tex.dispose();
          return;
        }
        tex.colorSpace = SRGBColorSpace;
        tex.minFilter = LinearFilter;
        tex.magFilter = LinearFilter;
        tex.anisotropy = 8;
        setTexture(tex);
        const { width, height } = tex.image as { width: number; height: number };
        if (width && height) setAspect(item.id, width / height);
      },
      undefined,
      () => !disposed && setFailed(true),
    );

    return () => {
      disposed = true;
    };
  }, [item.id, item.kind, item.src, setAspect]);

  useEffect(() => () => texture?.dispose(), [texture]);

  const aspect = item.kind === 'chart' ? CHART_ASPECT : (item.aspect ?? 1);
  /*
   * Fit inside a box rather than always claiming the full width. A portrait
   * photograph at 2.5 wide stands nearly four high and swallows the entire
   * room -- the first press photo the assistant fetched covered every card in
   * the ring. Tall pictures give up width instead.
   */
  const safe = Math.max(0.4, Math.min(3, aspect));
  const height = Math.min(WIDTH / safe, MAX_HEIGHT);
  const width = height * safe;

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: { x: width, y: height } },
      uRadius: { value: 0.07 },
      uColor: { value: new Color(PALETTE.signal) },
      uAccent: { value: new Color(PALETTE.ember) },
      uEnergy: { value: 0.5 },
      uSelect: { value: 0 },
      uWarn: { value: 0 },
      uFreeze: { value: 0 },
      uAspect: { value: aspect },
      uRipple: { value: -1 },
      uRippleAt: { value: { x: 0.5, y: 0.5 } },
    }),
    [width, height],
  );

  /** Arrives with a spring, like every other object here. */
  const motion = useMemo(
    () => ({
      position: new Spring3([0, 0.6, 0], SPRINGS.bouncy),
      scale: new Spring(0.35, SPRINGS.bouncy),
      opacity: new Spring(0, SPRINGS.crisp),
    }),
    [],
  );

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const t = interaction.sceneTime;

    if (item.kind === 'chart') {
      reveal.set(1);
      reveal.update(dt);
      const step = Math.round(reveal.value * REVEAL_STEPS);
      if (step !== revealStep) setRevealStep(step);
    }

    // Stacked frames sit back and to the side, dimmer and smaller.
    if (retiring) {
      // Down and back, to nothing. The spring makes it read as stepping away
      // rather than being switched off.
      motion.position.set(index * 0.3, -0.5, -index * STEP - 1.1);
      motion.scale.set(0.5);
      motion.opacity.set(0);
    } else if (stale) {
      /*
       * Reduced and parked to one side. Setting it straight back instead put
       * it among the ring cards, where a half-transparent chart interleaved
       * with a module face and read as clutter rather than as something
       * finished. Off to the left it stays available without competing.
       */
      motion.position.set(-1.95 - index * 0.22, -0.62 - index * 0.1, -0.55 - index * STEP);
      motion.scale.set(0.46 - index * 0.04);
      motion.opacity.set(0.26 - index * 0.07);
    } else if (pairSide) {
      /*
       * Placed by its own edge rather than by a fixed offset, so a tall
       * portrait and a wide chart still meet in the middle with an even gap
       * between them whatever their proportions.
       */
      const half = (width * PAIR_SCALE) / 2;
      motion.position.set(pairSide === 'left' ? -(half + 0.09) : half + 0.09, 0, 0);
      motion.scale.set(PAIR_SCALE);
      motion.opacity.set(1);
    } else {
      motion.position.set(index * 0.42, -index * 0.12, -index * STEP);
      motion.scale.set(focused ? 1 : 0.86 - index * 0.05);
      motion.opacity.set(focused ? 1 : 0.42 - index * 0.12);
    }
    motion.position.update(dt);
    motion.scale.update(dt);
    motion.opacity.update(dt);

    if (group.current) {
      group.current.position.set(
        motion.position.x.value,
        motion.position.y.value,
        motion.position.z.value,
      );
      const s = motion.scale.value;
      group.current.scale.set(s, s, s);
      // A slow breath, so a still image is never quite static.
      group.current.rotation.y = Math.sin(t * 0.18 + index) * 0.05;
      group.current.rotation.x = Math.sin(t * 0.13 + index * 2) * 0.025;
    }

    if (border.current) {
      const u = border.current.uniforms;
      u.uTime.value = t;
      u.uFreeze.value = interaction.freezeBlend;
      u.uEnergy.value = (focused ? 0.62 : 0.2) * motion.opacity.value;
      (u.uColor.value as Color).copy(envRuntime.glow);
      u.uWarn.value = failed ? 1 : 0;
    }

    if (plane.current) {
      const material = plane.current.material as { opacity: number };
      material.opacity = motion.opacity.value;
    }
  });

  return (
    <group ref={group}>
      {item.kind === 'shape' && item.shape ? (
        <ShapeView spec={item.shape} opacity={motion.opacity.value} />
      ) : (
        <mesh ref={plane}>
          <planeGeometry args={[width, height]} />
          <meshBasicMaterial
            map={chartTexture ?? texture ?? undefined}
            color={chartTexture || texture ? '#ffffff' : PALETTE.slate}
            transparent
            opacity={0}
            side={DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}

      {/*
        * Dismiss, on the object itself. The HUD already has a clear control,
        * but it clears everything and it is nowhere near the thing being
        * looked at -- so the frame carries its own, in the corner, where a
        * window's close button has always been.
        *
        * Only the frame in front gets one: a cross on a panel that is behind
        * another, reduced, or already leaving would be aiming at a target
        * that moves.
        */}
      {(focused || pairSide !== null) && !retiring && (
        <mesh
          name="media-close"
          position={[width / 2 - 0.11, height / 2 - 0.11, 0.03]}
          onPointerDown={(event) => {
            event.stopPropagation();
            dismiss(item.id);
            getAudio().collapse();
          }}
          onPointerOver={() => {
            document.body.style.cursor = 'pointer';
          }}
          onPointerOut={() => {
            document.body.style.cursor = '';
          }}
        >
          <planeGeometry args={[0.19, 0.19]} />
          <meshBasicMaterial
            map={getCloseTexture()}
            transparent
            opacity={motion.opacity.value}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}

      {/* The same border every card wears. */}
      <mesh position={[0, 0, 0.012]}>
        <planeGeometry args={[width * 1.05, height * 1.06]} />
        <shaderMaterial
          ref={border}
          vertexShader={FRAME_VERT}
          fragmentShader={FRAME_FRAG}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          blending={AdditiveBlending}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}
