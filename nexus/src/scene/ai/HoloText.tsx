'use client';

import { useCallback, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  type Points,
  type ShaderMaterial,
} from 'three';
import { HOLO_TEXT_FRAG, HOLO_TEXT_VERT } from '@/shaders/holoText';
import { PALETTE } from '@/config/theme';
import { interaction, voice } from '@/stores/runtime';
import { useSystemStore } from '@/stores/useSystemStore';
import { useAssistantStore } from '@/stores/useAssistantStore';
import { clamp } from '@/core/math';
import { rasterise } from './textRaster';

/**
 * The assistant's words, in space.
 *
 * There are no chat bubbles. Replies are rasterised, sampled, and flown onto
 * by a fixed pool of particles that assemble in reading order while the model
 * is still streaming.
 *
 * The component never re-renders: it subscribes to the store imperatively and
 * rewrites buffer attributes on a throttle. React is not in this loop.
 */

/*
 * Placement is tightly constrained. The camera sits at z 9.9 with a 42 degree
 * vertical FOV and looks slightly down, which leaves about 20 degrees of
 * headroom above the axis. The first version of this panel sat at 19.7 degrees
 * and was clipped by the top edge of the frame - visible only as a faint glow.
 *
 * Sitting it closer to the camera lets it drop to a comfortable 10 degrees
 * while staying large enough to read, and puts it in front of the ring rather
 * than behind the front card.
 */
const PANEL_WIDTH = 5.6;
const PANEL_Y = 1.9;
const PANEL_Z = 3.2;
/** Re-layout at reading speed, not at frame rate. */
const RELAYOUT_MS = 110;
/** How long the old turn takes to blow away. */
const DISSOLVE_S = 0.55;

/**
 * Dev-only diagnostics, mirroring window.__nexus.
 *
 * Kept because this component is the hardest thing in the project to debug by
 * eye: when nothing appears, the question is always "is it the data, the
 * uniforms, or the projection", and these three references answer it in one
 * console expression. Tree-shaken out of production builds.
 */
const probe = {
  frames: 0,
  rasters: 0,
  count: 0,
  text: 0,
  mesh: null as unknown,
  cam: null as unknown,
};
if (typeof window !== 'undefined' && process.env.NODE_ENV !== 'production') {
  (window as unknown as { __holo: typeof probe }).__holo = probe;
}

export function HoloText() {
  const material = useRef<ShaderMaterial>(null);
  const viewport = useThree((s) => s.size);
  const camera = useThree((s) => s.camera);
  const mesh = useRef<Points>(null);
  const profile = useSystemStore((s) => s.profile);

  const budget = useMemo(
    // Floor raised: below ~1800 the sampler is forced to a step wider than
    // the glyph strokes and the text stops being legible at all.
    () => clamp(Math.round(profile.particles * 0.9), 1800, 7000),
    [profile.particles],
  );

  const state = useRef({
    /** The text currently laid out on screen. */
    text: '',
    lastRaster: 0,
    activeCount: 0,
    dissolve: 0,
    dissolving: false,
    dirty: true,
  });

  const geometry = useMemo(() => {
    const geo = new BufferGeometry();
    const position = new Float32Array(budget * 3);
    const target = new Float32Array(budget * 3);
    const seed = new Float32Array(budget * 3);
    const spawn = new Float32Array(budget);
    const active = new Float32Array(budget);

    for (let i = 0; i < budget; i++) {
      seed[i * 3] = Math.random();
      seed[i * 3 + 1] = Math.random();
      seed[i * 3 + 2] = Math.random();
      spawn[i] = -999;
    }

    geo.setAttribute('position', new BufferAttribute(position, 3));
    geo.setAttribute('aTarget', new BufferAttribute(target, 3));
    geo.setAttribute('aSeed', new BufferAttribute(seed, 3));
    geo.setAttribute('aSpawn', new BufferAttribute(spawn, 1));
    geo.setAttribute('aActive', new BufferAttribute(active, 1));
    // The vertex shader computes position from aTarget, so real bounds are
    // unknowable up front - culling would pop the panel in and out.
    geo.boundingSphere = null;
    return geo;
  }, [budget]);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uWorldSize: { value: 0.02 },
      uPixelScale: { value: 800 },
      uDissolve: { value: 0 },
      uLevel: { value: 0 },
      uFreeze: { value: 0 },
      uColor: { value: new Color(PALETTE.signal) },
      uHot: { value: new Color(PALETTE.lumen) },
      uOpacity: { value: 1 },
    }),
    [],
  );

  /**
   * What should be on screen right now.
   *
   * Polled on the relayout tick rather than driven by a store subscription.
   * A subscription has to infer "has the rendered text diverged?" from an
   * event, and any missed or reordered event leaves the panel stuck showing
   * nothing with no way to recover. Reading the store is a couple of property
   * accesses every 110ms, and it is self-correcting by construction.
   */
  const readText = useCallback(() => {
    const store = useAssistantStore.getState();
    if (store.streaming) return store.streaming;
    /*
     * Hold the last thing the assistant said until the next reply actually
     * starts arriving. Blanking on the new question empties the panel for the
     * whole "thinking" phase - exactly when the user is waiting and looking at
     * it - and made the text flicker whenever the microphone picked up room
     * noise and opened a turn that produced nothing.
     */
    for (let i = store.history.length - 1; i >= 0; i--) {
      const message = store.history[i]!;
      if (message.role === 'model' && message.text) return message.text;
    }
    return '';
  }, []);

  useFrame((_, delta) => {
    probe.frames++;
    probe.mesh = mesh.current;
    probe.cam = camera;
    if (!material.current) return;
    const now = interaction.sceneTime;
    const s = state.current;
    probe.text = s.text.length;

    // Written through the LIVE material, not the object handed to the prop.
    const u = material.current.uniforms;
    u.uTime.value = now;
    // Recomputed each frame: the viewport can resize at any time.
    const fov = 'fov' in camera ? (camera as unknown as { fov: number }).fov : 42;
    u.uPixelScale.value = viewport.height / (2 * Math.tan((fov * Math.PI) / 360));
    u.uFreeze.value = interaction.freezeBlend;
    u.uLevel.value = voice.level;

    // --- dissolve ---------------------------------------------------------
    if (s.dissolving) {
      s.dissolve = Math.min(1, s.dissolve + delta / DISSOLVE_S);
      u.uDissolve.value = s.dissolve;
      if (s.dissolve >= 1) {
        s.dissolving = false;
        s.dissolve = 0;
        s.activeCount = 0;
        clearActive(geometry);
        u.uDissolve.value = 0;
        s.dirty = true;
      }
      return;
    }
    u.uDissolve.value = 0;

    // --- relayout ---------------------------------------------------------
    const elapsed = performance.now();
    if (elapsed - s.lastRaster < RELAYOUT_MS) return;
    s.lastRaster = elapsed;

    const next = readText();
    if (next === s.text && !s.dirty) return;

    // Text that no longer extends what is on screen belongs to a new turn, so
    // the old sentence is blown away rather than mutated into the new one.
    if (next !== s.text) {
      const extendsCurrent = s.text.length > 0 && next.startsWith(s.text);
      if (!extendsCurrent && s.activeCount > 0) {
        s.dissolving = true;
        s.text = next;
        return;
      }
      s.text = next;
    }
    s.dirty = false;

    if (!s.text) {
      if (s.activeCount > 0) {
        s.activeCount = 0;
        clearActive(geometry);
      }
      return;
    }

    const raster = rasterise(s.text, PANEL_WIDTH, budget);
    probe.rasters++;
    probe.count = raster.count;
    // Sized to just overlap its neighbours, so glyph strokes stay continuous
    // whatever sampling density the length of the answer forced.
    if (raster.spacing > 0) u.uWorldSize.value = raster.spacing * 1.6;
    applyRaster(geometry, raster, s.activeCount, now, budget);
    s.activeCount = raster.count;
  });

  return (
    <points
      ref={mesh}
      geometry={geometry}
      position={[0, PANEL_Y, PANEL_Z]}
      frustumCulled={false}
      renderOrder={900}
    >
      <shaderMaterial
        ref={material}
        vertexShader={HOLO_TEXT_VERT}
        fragmentShader={HOLO_TEXT_FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        /*
         * Depth testing OFF. The panel sits behind the front card in world
         * space, so a depth test hides the assistant's answer behind the very
         * module it is describing. This is a readout, not scenery - it reads
         * over the scene, like the HUD does.
         */
        depthTest={false}
        blending={AdditiveBlending}
        toneMapped={false}
      />
    </points>
  );
}

function clearActive(geometry: BufferGeometry): void {
  const active = geometry.getAttribute('aActive') as BufferAttribute;
  (active.array as Float32Array).fill(0);
  active.needsUpdate = true;
}

/**
 * Push new glyph targets into the buffers.
 *
 * Particles already on screen keep their spawn time and simply slide to their
 * new target, so reflowing a line does not restart the animation. Only newly
 * activated particles get a fresh, order-staggered spawn - that stagger is
 * what produces the left-to-right assembly.
 */
function applyRaster(
  geometry: BufferGeometry,
  raster: { points: Float32Array; count: number; order: Float32Array },
  previousCount: number,
  now: number,
  budget: number,
): void {
  const target = geometry.getAttribute('aTarget') as BufferAttribute;
  const spawn = geometry.getAttribute('aSpawn') as BufferAttribute;
  const active = geometry.getAttribute('aActive') as BufferAttribute;

  const targets = target.array as Float32Array;
  const spawns = spawn.array as Float32Array;
  const actives = active.array as Float32Array;

  const count = Math.min(raster.count, budget);
  for (let i = 0; i < count; i++) {
    targets[i * 3] = raster.points[i * 2]!;
    targets[i * 3 + 1] = raster.points[i * 2 + 1]!;
    targets[i * 3 + 2] = 0;
    if (i >= previousCount || actives[i] === 0) {
      spawns[i] = now + raster.order[i]! * 0.22;
      actives[i] = 1;
    }
  }
  for (let i = count; i < budget; i++) actives[i] = 0;

  target.needsUpdate = true;
  spawn.needsUpdate = true;
  active.needsUpdate = true;
}
