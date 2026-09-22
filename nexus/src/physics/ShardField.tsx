'use client';

import { useEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { BallCollider, RigidBody, type RapierRigidBody } from '@react-three/rapier';
import { AdditiveBlending, type Group } from 'three';
import { PALETTE } from '@/config/theme';
import { bus } from '@/stores/bus';
import { hash11 } from '@/core/math';

/**
 * Impact debris.
 *
 * A fixed pool of rigid bodies parked below the world until something needs
 * to break. Bursts recycle the oldest shards, so the count is a hard ceiling
 * no matter how enthusiastically the user throws cards around — allocation
 * during a burst is exactly the wrong moment to ask the GC for anything.
 */

const POOL = 36;
const PER_BURST = 9;
const LIFETIME = 2.4;
/** Parking position: outside the fog, inside the physics world. */
const PARKED: [number, number, number] = [0, -400, 0];

interface ShardState {
  bornAt: number;
  live: boolean;
}

export function ShardField() {
  const bodies = useRef<Array<RapierRigidBody | null>>(Array(POOL).fill(null));
  const visuals = useRef<Array<Group | null>>(Array(POOL).fill(null));
  const state = useRef<ShardState[]>(
    Array.from({ length: POOL }, () => ({ bornAt: -Infinity, live: false })),
  );
  const cursor = useRef(0);
  const clock = useRef(0);

  const shapes = useMemo(
    () =>
      Array.from({ length: POOL }, (_, i) => ({
        scale: 0.022 + hash11(i * 4.31) * 0.045,
        detail: hash11(i * 9.7) > 0.7 ? 1 : 0,
      })),
    [],
  );

  useEffect(() => {
    return bus.on('fx:burst', ({ position, power, warm }) => {
      const strength = 1.4 + power * 5.5;
      for (let n = 0; n < PER_BURST; n++) {
        const i = cursor.current;
        cursor.current = (cursor.current + 1) % POOL;
        const rb = bodies.current[i];
        if (!rb) continue;

        rb.setTranslation(
          {
            x: position[0] + (Math.random() - 0.5) * 0.16,
            y: position[1] + (Math.random() - 0.5) * 0.16,
            z: position[2] + (Math.random() - 0.5) * 0.16,
          },
          true,
        );
        // Spherical spray, biased upward so debris reads against the fog.
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(1 - Math.random() * 1.4);
        const speed = strength * (0.4 + Math.random() * 0.8);
        rb.setLinvel(
          {
            x: Math.sin(phi) * Math.cos(theta) * speed,
            y: Math.abs(Math.cos(phi)) * speed * 0.7 + 0.6,
            z: Math.sin(phi) * Math.sin(theta) * speed,
          },
          true,
        );
        rb.setAngvel(
          {
            x: (Math.random() - 0.5) * 14,
            y: (Math.random() - 0.5) * 14,
            z: (Math.random() - 0.5) * 14,
          },
          true,
        );

        state.current[i] = { bornAt: clock.current, live: true };
        const g = visuals.current[i];
        if (g) g.userData.warm = warm === true;
      }
    });
  }, []);

  useFrame((_, delta) => {
    clock.current += delta;
    for (let i = 0; i < POOL; i++) {
      const s = state.current[i]!;
      if (!s.live) continue;
      const age = (clock.current - s.bornAt) / LIFETIME;
      const g = visuals.current[i];
      if (g) {
        // Shrink out rather than fade out: at bloom strength a fading sprite
        // just turns grey, while a shrinking one reads as burning away.
        const k = Math.max(0, 1 - age * age);
        g.scale.setScalar(k);
      }
      if (age >= 1) {
        s.live = false;
        const rb = bodies.current[i];
        if (rb) {
          rb.setLinvel({ x: 0, y: 0, z: 0 }, false);
          rb.setAngvel({ x: 0, y: 0, z: 0 }, false);
          rb.setTranslation({ x: PARKED[0], y: PARKED[1], z: PARKED[2] }, false);
          rb.sleep();
        }
      }
    }
  });

  return (
    <group name="shards">
      {shapes.map((shape, i) => (
        <RigidBody
          key={i}
          ref={(r) => {
            bodies.current[i] = r;
          }}
          type="dynamic"
          colliders={false}
          position={PARKED}
          gravityScale={0.5}
          linearDamping={0.7}
          angularDamping={0.35}
          restitution={0.55}
          friction={0.2}
        >
          <BallCollider args={[shape.scale]} />
          <group
            ref={(g) => {
              visuals.current[i] = g;
            }}
            scale={0}
          >
            <mesh>
              <octahedronGeometry args={[shape.scale * 1.9, shape.detail]} />
              <meshBasicMaterial
                color={i % 7 === 0 ? PALETTE.lumen : PALETTE.signal}
                transparent
                opacity={0.9}
                blending={AdditiveBlending}
                depthWrite={false}
                toneMapped={false}
              />
            </mesh>
          </group>
        </RigidBody>
      ))}
    </group>
  );
}
