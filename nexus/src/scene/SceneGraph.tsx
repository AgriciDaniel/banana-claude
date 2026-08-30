'use client';

import { Suspense } from 'react';
import { Environment, Lightformer, AdaptiveEvents } from '@react-three/drei';
import { Physics } from '@react-three/rapier';
import { PALETTE } from '@/config/theme';
import { useSystemStore } from '@/stores/useSystemStore';
import { SceneDriver } from './SceneDriver';
import { Carousel } from './Carousel';
import { InteractionDriver } from './InteractionDriver';
import { HandReticle } from './HandReticle';
import { CameraRig } from '@/rendering/CameraRig';
import { AdaptiveQuality } from '@/rendering/AdaptiveQuality';
import { PostFX } from '@/rendering/PostFX';
import { Atmosphere } from '@/rendering/env/Atmosphere';
import { ParticleField } from '@/rendering/env/ParticleField';
import { LightBeams } from '@/rendering/env/LightBeams';
import { GroundGrid } from '@/rendering/env/GroundGrid';
import { Lighting } from '@/rendering/env/Lighting';
import { ShardField } from '@/physics/ShardField';
import { AiPresence } from './ai/AiPresence';
import { WakePulse } from './ai/WakePulse';
import { HoloText } from './ai/HoloText';
import { WeatherSky } from './modules/WeatherSky';
import { ModuleChart } from './modules/ModuleChart';
import { MarketFloor } from './modules/MarketFloor';
import { MediaStage } from './media/MediaStage';
import { Figure } from './avatar/Figure';
import { EnvironmentDriver } from '@/rendering/env/EnvironmentDriver';
import { WorldShift } from './fx/WorldShift';
import { GestureTrails } from './fx/GestureTrails';

/**
 * The scene graph.
 *
 * Composition only — every node here is a self-contained subsystem that reads
 * what it needs from the stores. Adding a module surface in phase 2 means
 * adding one node, not threading props through five layers.
 */
export function SceneGraph() {
  const profile = useSystemStore((s) => s.profile);

  return (
    <>
      {/* Drivers first: clock, camera, governor. All run before render. */}
      <SceneDriver />
      {/* Interpolates the world. Must run before anything reads envRuntime. */}
      <EnvironmentDriver />
      <CameraRig />
      <AdaptiveQuality />
      <AdaptiveEvents />

      {/* Depth cue for lit materials. The atmosphere sphere handles the rest. */}
      {/* Density is overwritten every frame by the environment and weather. */}
      <fogExp2 attach="fog" args={[PALETTE.void, 0.042]} />

      <Atmosphere />
      <Lighting />

      {/*
        Reflections come from an environment rendered out of these lightformers,
        not from an HDRI on a CDN. Offline-safe, art-directed, and it means the
        glass reflects the same blue key light the scene is actually lit by.
      */}
      <Environment resolution={profile.liveReflections ? 256 : 128} frames={1}>
        <Lightformer
          form="rect"
          intensity={2.6}
          color={PALETTE.signal}
          position={[-6, 4, -8]}
          scale={[12, 8, 1]}
        />
        <Lightformer
          form="rect"
          intensity={1.4}
          color={PALETTE.lumen}
          position={[7, 2, -6]}
          scale={[8, 10, 1]}
        />
        <Lightformer
          form="circle"
          intensity={3.2}
          color={PALETTE.lumen}
          position={[0, 9, 0]}
          scale={[7, 7, 1]}
          rotation={[Math.PI / 2, 0, 0]}
        />
        <Lightformer
          form="rect"
          intensity={0.9}
          color={PALETTE.core}
          position={[0, -5, 3]}
          scale={[14, 6, 1]}
          rotation={[-Math.PI / 2, 0, 0]}
        />
      </Environment>

      {/*
        Phase 3. The weather module does not draw a widget - it changes the
        room. Precipitation, fog density and storm light all come from the live
        forecast for wherever the viewer actually is.
      */}
      <WeatherSky />

      {/* Expanded modules get their numbers as objects, not just as a panel. */}
      <ModuleChart />

      <ParticleField count={profile.particles} />
      <LightBeams count={profile.beams} />
      <GroundGrid />
      {/* Stocks turns the ground into a trading surface. */}
      <MarketFloor />

      {/*
        Zero-ish gravity. Cards are objects with mass in a room that is barely
        pulling on them: a dropped card sinks and drifts back rather than
        falling, which is the only physical behaviour that reads as "spatial"
        instead of "broken".
      */}
      <Suspense fallback={null}>
        <Physics
          gravity={[0, -1.2, 0]}
          timeStep="vary"
          numSolverIterations={profile.physicsSubsteps * 4}
          interpolate
        >
          <Carousel />
          <ShardField />
        </Physics>
      </Suspense>

      <InteractionDriver />
      <HandReticle />
      {/* Motion leaves light behind it. */}
      <GestureTrails />

      {/*
        Phase 2. Additive: none of the nodes above know these exist. The
        assistant reads the same runtime bus everything else does and drives
        the ring through the same public API a hand gesture uses.
      */}
      <WakePulse />
      <WorldShift />
      <AiPresence />
      <HoloText />
      {/* Images, video and solids, standing in the room. */}
      <MediaStage />
      {/* And someone standing beside them, to point at the one that matters. */}
      <Figure />

      <PostFX />
    </>
  );
}
