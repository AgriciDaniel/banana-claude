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
import { Spring, Spring3 } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import type { MediaItem } from '@/media/types';
import { ShapeView } from './ShapeView';

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
/** Depth offsets for the stack behind the focused frame. */
const STEP = 0.34;

export function MediaFrame({ item, index }: { item: MediaItem; index: number }) {
  const group = useRef<Group>(null);
  const plane = useRef<Mesh>(null);
  const border = useRef<ShaderMaterial>(null);
  const [texture, setTexture] = useState<Texture | null>(null);
  const [failed, setFailed] = useState(false);
  const setAspect = useMediaStore((s) => s.setAspect);

  const focused = index === 0;

  // --- texture ------------------------------------------------------------
  useEffect(() => {
    if (item.kind === 'shape' || !item.src) return;
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

  const aspect = item.aspect ?? 1;
  const height = WIDTH / Math.max(0.4, Math.min(3, aspect));

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSize: { value: { x: WIDTH, y: height } },
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
    [height, aspect],
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

    // Stacked frames sit back and to the side, dimmer and smaller.
    motion.position.set(index * 0.42, -index * 0.12, -index * STEP);
    motion.scale.set(focused ? 1 : 0.86 - index * 0.05);
    motion.opacity.set(focused ? 1 : 0.42 - index * 0.12);
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
          <planeGeometry args={[WIDTH, height]} />
          <meshBasicMaterial
            map={texture ?? undefined}
            color={texture ? '#ffffff' : PALETTE.slate}
            transparent
            opacity={0}
            side={DoubleSide}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      )}

      {/* The same border every card wears. */}
      <mesh position={[0, 0, 0.012]}>
        <planeGeometry args={[WIDTH * 1.05, height * 1.06]} />
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
