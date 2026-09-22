'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Color, DoubleSide, type Mesh, type ShaderMaterial } from 'three';
import { MARKET_FRAG, MARKET_VERT } from '@/shaders/marketGrid';
import { PALETTE } from '@/config/theme';
import { interaction } from '@/stores/runtime';
import { envRuntime } from '@/stores/useEnvironmentStore';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useFeedStore } from '@/modules/store';
import type { StocksData } from '@/modules/types';
import { clamp, damp } from '@/core/math';

/**
 * The floor becomes the market.
 *
 * Fades in over the normal grid when Stocks is expanded, carrying one lane per
 * real holding. Lane colour is the day's direction, scroll speed is the size
 * of the move — so a volatile morning is visible in peripheral vision without
 * reading a single number.
 */

const LANES = 8;
const EXTENT = 46;

export function MarketFloor() {
  const mesh = useRef<Mesh>(null);
  const material = useRef<ShaderMaterial>(null);

  const expandedId = useCarouselStore((s) => s.expandedId);
  const feed = useFeedStore((s) => s.feeds.stocks);
  const stocks = feed?.data as StocksData | undefined;

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uAmount: { value: 0 },
      uFade: { value: EXTENT * 0.5 },
      uUp: { value: new Color(PALETTE.lock) },
      uDown: { value: new Color(PALETTE.ember) },
      uBase: { value: new Color(PALETTE.signal) },
      // Fixed-length array: GLSL needs a compile-time size.
      uChange: { value: new Array(LANES).fill(0) as number[] },
    }),
    [],
  );

  useFrame((_, delta) => {
    const mat = material.current;
    if (!mat) return;
    const dt = delta > 0.05 ? 0.05 : delta;
    const u = mat.uniforms;

    const wanted = expandedId === 'stocks' && stocks ? 1 : 0;
    u.uAmount.value = damp(u.uAmount.value as number, wanted, 2.2, dt);

    if (mesh.current) {
      mesh.current.visible = (u.uAmount.value as number) > 0.01;
      // Sits a hair above the world's own floor, whatever height that is.
      mesh.current.position.y = envRuntime.floorY + 0.02;
    }
    if (!mesh.current?.visible) return;

    u.uTime.value = interaction.sceneTime;
    (u.uBase.value as Color).copy(envRuntime.grid);

    // Real day changes, clamped so one wild mover cannot flatten the rest.
    const changes = u.uChange.value as number[];
    for (let i = 0; i < LANES; i++) {
      const holding = stocks?.holdings[i];
      changes[i] = holding ? clamp(holding.changePct / 4, -1, 1) : 0;
    }
  });

  return (
    <mesh
      ref={mesh}
      visible={false}
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, -3, 0]}
      renderOrder={-480}
    >
      <planeGeometry args={[EXTENT, EXTENT, 1, 1]} />
      <shaderMaterial
        ref={material}
        vertexShader={MARKET_VERT}
        fragmentShader={MARKET_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        side={DoubleSide}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </mesh>
  );
}
