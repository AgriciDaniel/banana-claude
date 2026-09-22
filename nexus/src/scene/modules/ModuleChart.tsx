'use client';

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { AdditiveBlending, Color, InstancedMesh, Matrix4, Object3D, type Group } from 'three';
import { PALETTE, SPACE } from '@/config/theme';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useFeedStore } from '@/modules/store';
import { interaction } from '@/stores/runtime';
import { Spring } from '@/animation/Spring';
import { SPRINGS } from '@/animation/presets';
import { damp } from '@/core/math';
import type { InstagramData, StocksData, SystemData, WeatherData } from '@/modules/types';

/**
 * Charts, in the room.
 *
 * When a module expands, its numbers get a physical presence beside the card
 * rather than living only in the DOM rail. Bars rise out of the floor on
 * springs, so the data arrives with the same weight as everything else in the
 * environment.
 *
 * One instanced mesh serves every module: at these counts the interesting cost
 * is per-object overhead, not fill rate, and a single buffer means switching
 * modules never reallocates.
 */

const MAX_BARS = 32;
const BAR_W = 0.13;
const GAP = 0.055;
const HEIGHT = 1.35;

interface Series {
  values: number[];
  /** Per-bar tint: 1 = positive/accent, 0 = neutral. */
  accents: number[];
  label: string;
}

/** What each module contributes, normalised to 0..1. */
function readSeries(id: string | null, feed: unknown): Series | null {
  if (!id || !feed) return null;
  const data = (feed as { data?: unknown }).data;
  if (!data) return null;

  if (id === 'stocks') {
    const d = data as StocksData;
    if (d.holdings.length === 0) return null;
    const max = Math.max(...d.holdings.map((h) => h.value));
    return {
      values: d.holdings.map((h) => h.value / max),
      accents: d.holdings.map((h) => (h.pnl >= 0 ? 1 : 0)),
      label: 'POSITION VALUE',
    };
  }

  if (id === 'instagram') {
    const d = data as InstagramData;
    if (d.growth.length === 0) return null;
    const max = Math.max(...d.growth.map((g) => Math.abs(g.value)), 1);
    return {
      values: d.growth.slice(-MAX_BARS).map((g) => Math.abs(g.value) / max),
      accents: d.growth.slice(-MAX_BARS).map((g) => (g.value >= 0 ? 1 : 0)),
      label: 'FOLLOWER GROWTH',
    };
  }

  if (id === 'weather') {
    const d = data as WeatherData;
    if (d.hourly.length === 0) return null;
    const temps = d.hourly.map((h) => h.temp);
    const min = Math.min(...temps);
    const span = Math.max(1, Math.max(...temps) - min);
    return {
      values: temps.map((v) => 0.12 + ((v - min) / span) * 0.88),
      accents: d.hourly.map((h) => (h.precip > 0.05 ? 0 : 1)),
      label: 'NEXT 24 HOURS',
    };
  }

  if (id === 'system') {
    const d = data as SystemData;
    // A live rolling readout rather than a history we do not keep.
    const parts = [
      d.fps / 120,
      Math.min(1, d.drawCalls / 200),
      Math.min(1, d.cores / 24),
      d.battery ? d.battery.level : 1,
      d.heapUsedMb && d.heapLimitMb ? d.heapUsedMb / d.heapLimitMb : 0.2,
      d.storage ? d.storage.usedMb / Math.max(1, d.storage.quotaMb) : 0.1,
    ];
    return {
      values: parts,
      accents: parts.map((v, i) => (i === 4 || i === 5 ? (v > 0.8 ? 0 : 1) : 1)),
      label: 'DIAGNOSTICS',
    };
  }

  return null;
}

const dummy = new Object3D();
const matrix = new Matrix4();

export function ModuleChart() {
  const group = useRef<Group>(null);
  const bars = useRef<InstancedMesh>(null);

  const expandedId = useCarouselStore((s) => s.expandedId);
  const feed = useFeedStore((s) => (expandedId ? s.feeds[expandedId] : undefined));

  const series = useMemo(() => readSeries(expandedId, feed), [expandedId, feed]);

  /** One spring per bar; they rise in sequence rather than together. */
  const springs = useMemo(
    () => Array.from({ length: MAX_BARS }, () => new Spring(0, SPRINGS.elastic)),
    [],
  );

  const colors = useMemo(() => ({ up: new Color(PALETTE.signal), down: new Color(PALETTE.ember) }), []);
  const visible = useRef(0);

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const mesh = bars.current;
    if (!mesh || !group.current) return;

    const active = series?.values.length ?? 0;
    visible.current = damp(visible.current, active > 0 ? 1 : 0, 5, dt);

    group.current.visible = visible.current > 0.01;
    if (!group.current.visible) return;

    // Sit to the left of the expanded card, angled toward the viewer.
    group.current.position.set(-2.55, -0.55, SPACE.orbitRadius + 1.1);
    group.current.rotation.y = 0.42;

    const count = Math.min(active, MAX_BARS);
    const width = count * BAR_W + Math.max(0, count - 1) * GAP;

    for (let i = 0; i < MAX_BARS; i++) {
      const spring = springs[i]!;
      const target = i < count ? (series!.values[i] ?? 0) : 0;
      // Stagger: each bar starts a beat after the one before it.
      spring.set(target * visible.current);
      spring.update(dt);

      const height = Math.max(0.004, spring.value * HEIGHT);
      const x = -width / 2 + i * (BAR_W + GAP) + BAR_W / 2;

      dummy.position.set(x, height / 2, 0);
      dummy.scale.set(BAR_W, height, BAR_W);
      dummy.rotation.set(0, 0, 0);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);

      const accent = series?.accents[i] ?? 1;
      mesh.setColorAt(i, accent > 0.5 ? colors.up : colors.down);
    }

    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    void matrix;
    void interaction.sceneTime;
  });

  return (
    <group ref={group} name="module-chart" visible={false}>
      <instancedMesh ref={bars} args={[undefined, undefined, MAX_BARS]} frustumCulled={false}>
        <boxGeometry args={[1, 1, 1]} />
        <meshBasicMaterial
          transparent
          opacity={0.72}
          blending={AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </instancedMesh>

      {/* Baseline, so the bars read as standing on something. */}
      <mesh position={[0, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[MAX_BARS * (BAR_W + GAP), 0.02]} />
        <meshBasicMaterial
          color={PALETTE.signal}
          transparent
          opacity={0.35}
          blending={AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </mesh>
    </group>
  );
}
