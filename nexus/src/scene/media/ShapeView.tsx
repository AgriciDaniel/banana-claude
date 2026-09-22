"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Color, DoubleSide, type Mesh, type MeshPhysicalMaterial } from "three";
import { envRuntime } from "@/stores/useEnvironmentStore";
import { interaction } from "@/stores/runtime";
import { clamp } from "@/core/math";
import type { ShapeSpec } from "@/media/types";

/**
 * A parametric solid, summoned by description.
 *
 * The assistant cannot hand back geometry, but it can hand back a few numbers
 * and a name — so shapes are described rather than modelled. Everything is
 * clamped, because a scale or spin the model picked badly should look odd
 * rather than fill the room or induce nausea.
 */
/**
 * Every primitive below is authored at roughly unit size, which turned out to
 * fill the entire viewport once placed two metres from the camera. This brings
 * a scale of 1 down to something that sits inside the media frame rather than
 * eclipsing the ring behind it.
 */
const FIT = 0.55;

export function ShapeView({
  spec,
  opacity,
}: {
  spec: ShapeSpec;
  opacity: number;
}) {
  const mesh = useRef<Mesh>(null);
  const material = useRef<MeshPhysicalMaterial>(null);

  const scale = clamp(spec.scale ?? 1, 0.3, 3) * FIT;
  const spin = clamp(spec.spin ?? 0.12, -2, 2);
  const glass = clamp(spec.glass ?? 0.35, 0, 1);

  const tint = useMemo(
    () => (spec.color ? new Color(spec.color) : null),
    [spec.color],
  );

  useFrame((_, delta) => {
    const t = interaction.sceneTime;
    const live = 1 - interaction.freezeBlend * 0.92;

    if (mesh.current) {
      mesh.current.rotation.y = t * spin * Math.PI * 2 * live;
      mesh.current.rotation.x = Math.sin(t * 0.31) * 0.22;
      mesh.current.scale.setScalar(scale * (0.94 + Math.sin(t * 0.7) * 0.06));
    }

    if (material.current) {
      material.current.opacity = opacity;
      // Untinted shapes take the world's colour, so they belong to it.
      if (!tint) material.current.color.copy(envRuntime.glow);
      material.current.emissiveIntensity = 0.25 + Math.sin(t * 1.1) * 0.08;
      void delta;
    }
  });

  return (
    <mesh ref={mesh}>
      {spec.kind === "sphere" && <sphereGeometry args={[0.62, 48, 32]} />}
      {spec.kind === "box" && <boxGeometry args={[0.95, 0.95, 0.95]} />}
      {spec.kind === "torus" && <torusGeometry args={[0.52, 0.19, 24, 64]} />}
      {spec.kind === "knot" && (
        <torusKnotGeometry args={[0.45, 0.15, 128, 24]} />
      )}
      {spec.kind === "icosahedron" && <icosahedronGeometry args={[0.68, 0]} />}
      {spec.kind === "cylinder" && (
        <cylinderGeometry args={[0.45, 0.45, 1.05, 40]} />
      )}
      {spec.kind === "cone" && <coneGeometry args={[0.55, 1.1, 40]} />}
      {spec.kind === "ring" && <ringGeometry args={[0.32, 0.66, 64]} />}

      <meshPhysicalMaterial
        ref={material}
        color={tint ?? undefined}
        emissive={tint ?? undefined}
        emissiveIntensity={0.25}
        metalness={0.1}
        roughness={0.18}
        transmission={glass * 0.85}
        thickness={0.6}
        ior={1.35}
        clearcoat={1}
        clearcoatRoughness={0.2}
        wireframe={spec.wireframe === true}
        transparent
        opacity={opacity}
        side={DoubleSide}
      />
    </mesh>
  );
}
