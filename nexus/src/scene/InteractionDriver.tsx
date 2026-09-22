'use client';

import { useEffect, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Vector3 } from 'three';
import { MODULES } from '@/config/modules';
import { SPACE } from '@/config/theme';
import { carousel, gestureSnapshot, interaction, pendingImpulses, pointer } from '@/stores/runtime';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { bus } from '@/stores/bus';
import { log } from '@/stores/useLogStore';
import { useMediaStore } from '@/stores/useMediaStore';
import { clearMedia } from '@/media/actions';
import { getAudio } from '@/audio/AudioEngine';
import { ring } from './ringController';
import { liveRadius, slotAngle, slotPosition } from './cardMath';
import { clamp, clamp01, damp } from '@/core/math';
import type { GestureEvent } from '@/gesture/types';
import { t, useLocaleStore } from '@/i18n';
import { localizeModule } from '@/i18n/modules';

/**
 * Interaction.
 *
 * The single place where an intention becomes a change to the world. The
 * gesture engine does not know what a card is; the cards do not know what a
 * pinch is. This is the seam between them, and keeping it a seam is what will
 * let phase two add voice or gaze without touching either side.
 */

const AIM_NEAR = 2.3;
const AIM_FAR = 5.2;
/** Aim must land within this of a card's centre to count as pointing at it. */
const HIT_RADIUS = 1.15;
/** Release speed above which a card actually flies instead of snapping home. */
const THROW_SPEED = 1.4;

/** Localised display name for a module id, for the log. */
function nameOf(id: string): string {
  const mod = MODULES.find((m) => m.id === id);
  if (!mod) return id.toUpperCase();
  return localizeModule(mod, useLocaleStore.getState().locale).name.toUpperCase();
}

const vAim = new Vector3();
const vDir = new Vector3();
const vCard = new Vector3();
const slot: [number, number, number] = [0, 0, 0];

export function InteractionDriver() {
  const camera = useThree((s) => s.camera);
  const audio = getAudio();

  /** World-space velocity of the aim point, for throw momentum. */
  const aimVelocity = useRef(new Vector3());
  const prevAim = useRef(new Vector3());
  const hoverSound = useRef<string | null>(null);

  useFrame((_, delta) => {
    const dt = delta > 0.05 ? 0.05 : delta;
    const hand = gestureSnapshot.primary;
    const input = useSystemStore.getState().input;

    // --- where is the user pointing? --------------------------------------
    let ndcX: number;
    let ndcY: number;
    let distance: number;

    if (hand && input === 'hand') {
      ndcX = hand.palm.x * 2 - 1;
      ndcY = -(hand.palm.y * 2 - 1);
      // Apparent hand size is the depth axis: reaching forward pulls the
      // reticle toward the viewer, which is what makes pull/push legible.
      distance = AIM_FAR - clamp01(hand.depth) * (AIM_FAR - AIM_NEAR);
    } else {
      ndcX = pointer.ndcX;
      ndcY = pointer.ndcY;
      distance = (AIM_NEAR + AIM_FAR) * 0.5;
    }

    vAim.set(ndcX, ndcY, 0.5).unproject(camera);
    vDir.copy(vAim).sub(camera.position).normalize();
    vAim.copy(camera.position).addScaledVector(vDir, distance);

    // Smooth the aim itself — the reticle must never jitter even if tracking does.
    interaction.aimX = damp(interaction.aimX, vAim.x, 18, dt);
    interaction.aimY = damp(interaction.aimY, vAim.y, 18, dt);
    interaction.aimZ = damp(interaction.aimZ, vAim.z, 18, dt);

    aimVelocity.current.set(
      (interaction.aimX - prevAim.current.x) / dt,
      (interaction.aimY - prevAim.current.y) / dt,
      (interaction.aimZ - prevAim.current.z) / dt,
    );
    prevAim.current.set(interaction.aimX, interaction.aimY, interaction.aimZ);

    // --- what is it pointing at? ------------------------------------------
    const store = useCarouselStore.getState();
    if (!store.draggingId && !store.expandedId) {
      const hit = nearestCard();
      if (hit !== store.hoveredId) {
        store.setHovered(hit);
        if (hit && hit !== hoverSound.current) {
          audio.hover(clamp(interaction.aimX / 3, -1, 1));
          hoverSound.current = hit;
        }
        if (!hit) hoverSound.current = null;
      }
    }

    // --- keep the grab offset attached to the card ------------------------
    if (store.draggingId) {
      interaction.grabbedId = store.draggingId;
    } else {
      interaction.grabbedId = null;
    }
  });

  // --- discrete gestures --------------------------------------------------
  useEffect(() => {
    const off = bus.on('gesture', (event: GestureEvent) => {
      const cards = useCarouselStore.getState();
      const pan = clamp(interaction.aimX / 3, -1, 1);

      switch (event.kind) {
        case 'swipe_left':
          ring.rotate(1, event.magnitude ?? 1);
          audio.whoosh(-1, clamp(event.confidence + 0.4, 0.4, 1.4));
          log.gesture(t('log.swipeLeft', { pct: (event.confidence * 100) | 0 }));
          break;

        case 'swipe_right':
          ring.rotate(-1, event.magnitude ?? 1);
          audio.whoosh(1, clamp(event.confidence + 0.4, 0.4, 1.4));
          log.gesture(t('log.swipeRight', { pct: (event.confidence * 100) | 0 }));
          break;

        case 'pinch_start': {
          const target = cards.hoveredId ?? MODULES[cards.focusedIndex]?.id ?? null;
          if (!target) {
            audio.deny();
            break;
          }
          // Offset is captured once, so the card keeps the grip point it was
          // grabbed by instead of snapping its centre to the hand.
          cardWorldPosition(target, vCard);
          interaction.grabOffset[0] = vCard.x - interaction.aimX;
          interaction.grabOffset[1] = vCard.y - interaction.aimY;
          interaction.grabOffset[2] = vCard.z - interaction.aimZ;
          cards.beginDrag(target);
          audio.grab(pan);
          log.gesture(t('log.grab', { module: nameOf(target) }));
          break;
        }

        case 'pinch_end': {
          const id = cards.draggingId;
          if (!id) break;
          const v = aimVelocity.current;
          const speed = v.length();
          const thrown = speed > THROW_SPEED;

          if (thrown) {
            // Hand velocity becomes body velocity, damped so a flick does not
            // put a card in the next postcode.
            pendingImpulses.set(id, {
              lin: [v.x * 0.45, v.y * 0.45 + 0.3, v.z * 0.45],
              ang: [v.y * 0.4, v.x * 0.5, (Math.random() - 0.5) * 1.6],
            });
            bus.emit('card:released', { id, speed });
            bus.emit('fx:burst', {
              position: [interaction.aimX, interaction.aimY, interaction.aimZ],
              power: clamp01(speed / 6),
            });
            log.gesture(t('log.throw', { speed: speed.toFixed(1) }));
          } else {
            log.gesture(t('log.release', { module: nameOf(id) }));
          }

          cards.endDrag(id, thrown);
          audio.release(clamp01(speed / 6), pan);
          break;
        }

        case 'pull': {
          const id = cards.selectedId ?? cards.hoveredId ?? MODULES[cards.focusedIndex]?.id;
          if (!id) break;
          if (cards.expandedId === id) break;
          cards.expand(id);
          audio.expand();
          log.ok(t('log.expand', { module: nameOf(id) }));
          break;
        }

        /*
         * A snap means "back", one level at a time: drop what is on the
         * display, else close what is open, else clear the selection.
         *
         * It deliberately does NOT thaw a freeze. Charging a snap closes the
         * hand, which breaks the palm-hold latch on its own a frame or two
         * earlier -- so a "thaw on snap" branch could never be reached, and
         * writing one would only suggest a path that does not exist.
         */
        case 'snap': {
          if (useMediaStore.getState().stack.length > 0) {
            clearMedia();
            log.ok(t('log.snapBack'));
            break;
          }
          if (cards.expandedId) {
            log.ok(t('log.collapse', { module: nameOf(cards.expandedId) }));
            cards.collapse();
            audio.collapse();
            break;
          }
          if (cards.selectedId) {
            cards.select(null);
            audio.collapse();
            log.ok(t('log.snapBack'));
          }
          break;
        }

        case 'push': {
          if (!cards.expandedId) {
            // Nothing to collapse — push doubles as "deselect".
            if (cards.selectedId) {
              cards.select(null);
              audio.collapse();
            }
            break;
          }
          log.ok(t('log.collapse', { module: nameOf(cards.expandedId) }));
          cards.collapse();
          audio.collapse();
          break;
        }

        case 'palm_hold':
          interaction.frozen = true;
          interaction.frozenAt = event.at;
          ring.setLocked(true);
          audio.freeze();
          log.warn(t('log.frozen'));
          break;

        case 'palm_release':
          if (!interaction.frozen) break;
          interaction.frozen = false;
          ring.setLocked(false);
          audio.thaw();
          log.ok(t('log.resumed'));
          break;

        // --- two-handed ---------------------------------------------------
        case 'two_group': {
          // Gather: bring the ring in and pull the focused module forward.
          const id = MODULES[cards.focusedIndex]?.id;
          if (id) cards.select(id);
          audio.confirm();
          bus.emit('fx:burst', {
            position: [0, SPACE.orbitHeight, SPACE.orbitRadius * 0.5],
            power: 0.5,
          });
          log.gesture(t('log.twoGroup'));
          break;
        }

        case 'two_split': {
          // Fan out: drop any selection so the whole ring is legible at once.
          cards.select(null);
          if (cards.expandedId) cards.collapse();
          audio.whoosh(1, 1.2);
          log.gesture(t('log.twoSplit'));
          break;
        }

        case 'two_select': {
          // Multi-select: mark the three modules currently facing the viewer.
          const picked = frontThree();
          cards.setMultiSelection(picked);
          audio.confirm();
          log.gesture(t('log.twoSelect', { count: picked.length }));
          break;
        }

        case 'circle':
          // Reserved for the phase-two reasoning surface. It is recognised and
          // acknowledged now so the vocabulary is already trained by then.
          audio.arcane();
          log.sys(t('log.circle'));
          bus.emit('fx:burst', {
            position: [interaction.aimX, interaction.aimY, interaction.aimZ],
            power: 0.55,
          });
          break;

        case 'open_hand':
          if (cards.selectedId && !cards.expandedId && !cards.draggingId) {
            cards.select(null);
          }
          break;

        case 'closed_hand':
          break;

        default:
          break;
      }
    });
    return off;
  }, [audio]);

  return null;
}

/** The three module ids closest to front and centre. */
function frontThree(): string[] {
  return MODULES.map((mod, i) => ({
    id: mod.id,
    front: Math.cos(slotAngle(i, carousel.angle)),
  }))
    .sort((a, b) => b.front - a.front)
    .slice(0, 3)
    .map((entry) => entry.id);
}

/** Nearest card to the aim point, or null when the user is pointing at nothing. */
function nearestCard(): string | null {
  let best: string | null = null;
  let bestDist = HIT_RADIUS;
  for (let i = 0; i < MODULES.length; i++) {
    slotPosition(slotAngle(i, carousel.angle), slot, liveRadius(interaction.spread));
    // Cards behind the viewer are never hit targets, however close they get.
    if (slot[2] < -SPACE.orbitRadius * 0.35) continue;
    const dx = slot[0] - interaction.aimX;
    const dy = slot[1] - interaction.aimY;
    const dz = slot[2] - interaction.aimZ;
    const d = Math.hypot(dx, dy, dz * 0.55);
    if (d < bestDist) {
      bestDist = d;
      best = MODULES[i]!.id;
    }
  }
  return best;
}

function cardWorldPosition(id: string, out: Vector3): void {
  const index = MODULES.findIndex((m) => m.id === id);
  if (index < 0) {
    out.set(0, 0, 0);
    return;
  }
  slotPosition(slotAngle(index, carousel.angle), slot, liveRadius(interaction.spread));
  out.set(slot[0], slot[1], slot[2]);
}
