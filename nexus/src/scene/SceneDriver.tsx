'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useEffect, useRef } from 'react';
import { interaction, perf } from '@/stores/runtime';
import { damp, RollingMean } from '@/core/math';

/**
 * The clock.
 *
 * Runs before everything else (negative priority) and is the only place that
 * advances scene time or samples the renderer. Two consequences worth stating:
 *
 *   - every shader reads `interaction.sceneTime`, never its own clock, so a
 *     freeze slows the entire world coherently instead of per-material;
 *   - frame statistics are read once per frame, not once per consumer.
 */
export function SceneDriver() {
  const gl = useThree((s) => s.gl);
  const frameMs = useRef(new RollingMean(30));
  const fps = useRef(new RollingMean(45));
  const last = useRef(0);

  /*
   * The post pipeline issues several gl.render() calls per frame, and each one
   * resets renderer.info. Left on auto, the stats report whatever the final
   * pass happened to draw — which is why an untouched build proudly claims one
   * draw call. Take manual control and reset once per frame instead.
   */
  useEffect(() => {
    gl.info.autoReset = false;
    return () => {
      gl.info.autoReset = true;
    };
  }, [gl]);

  useFrame((state, delta) => {
    const dt = delta > 0.1 ? 0.1 : delta;

    // Freeze is a blend, not a boolean, so the world eases to a halt.
    interaction.freezeBlend = damp(interaction.freezeBlend, interaction.frozen ? 1 : 0, 4.5, dt);
    interaction.sceneTime += dt * (1 - interaction.freezeBlend * 0.94);

    const now = state.clock.elapsedTime * 1000;
    if (last.current > 0) {
      const ms = now - last.current;
      // Both readouts come off the SAME mean. Averaging milliseconds and
      // averaging their reciprocals separately lets one long stall put the two
      // numbers into open disagreement, which makes the HUD look broken.
      frameMs.current.push(ms);
      perf.fps = fps.current.push(1000 / Math.max(ms, 0.001));
      perf.frameMs = 1000 / Math.max(perf.fps, 0.001);
    }
    last.current = now;

    // Read the totals accumulated across every pass of the PREVIOUS frame,
    // then clear for the frame about to be drawn.
    const info = gl.info;
    perf.drawCalls = info.render.calls;
    perf.triangles = info.render.triangles;
    perf.programs = info.programs?.length ?? 0;
    perf.sinceTierChange++;
    info.reset();
  }, -100);

  return null;
}
