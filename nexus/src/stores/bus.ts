import { createBus } from '@/core/eventBus';
import type { GestureEvent } from '@/gesture/types';

/**
 * Application-wide signal bus. Deliberately narrow: only things that must
 * cross a layer boundary without a React render belong here.
 */
export interface NexusEvents {
  gesture: GestureEvent;
  /** A card changed discrete state — drives audio + log. */
  'card:state': { id: string; state: string };
  /** A card was released with enough momentum to fly. */
  'card:released': { id: string; speed: number };
  /** A card came to rest back in its slot. */
  'card:settled': { id: string };
  /** Carousel snapped to a new slot. */
  'carousel:snap': { index: number; direction: -1 | 1 };
  /** Emit a shard burst at a world position. */
  'fx:burst': { position: [number, number, number]; power: number; warm?: boolean };
  /** Quality governor moved a tier. */
  'quality:change': { tier: string; direction: 'up' | 'down' };

  // --- phase 2: assistant ------------------------------------------------
  /** Wake requested. `source` distinguishes the phrase from the gesture. */
  'ai:wake': { source: 'phrase' | 'gesture' | 'manual' };
  /** Assistant returned to standby. */
  'ai:sleep': { reason: 'timeout' | 'command' | 'error' | 'manual' };
  /** Assistant lifecycle state changed. Drives HUD, scene glow and audio. */
  'ai:status': { status: string; previous: string };
  /** A chunk of streamed model text. Accumulated by the holographic text. */
  'ai:token': { text: string; done: boolean };
  /** A complete sentence is ready to speak. */
  'ai:sentence': { text: string; index: number };
  /** Speech amplitude envelope, 0..1, sampled while the assistant talks. */
  'ai:level': { level: number };
  /** The user cut in while the assistant was speaking. */
  'ai:interrupt': Record<string, never>;
  /** A resolved command was executed against the scene. */
  'ai:command': { name: string; argument: string | null; ok: boolean };

  // --- phase 4: delight ---------------------------------------------------
  /** The world changed. `source` says whether a module or the user did it. */
  'env:change': { id: string; source: 'module' | 'user' };
  /** A ripple should spread from this point on a card surface. */
  'fx:ripple': { position: [number, number, number]; strength: number };

  // --- phase 5: spatial media ---------------------------------------------
  /** Something was placed in the room. */
  'media:show': { id: string; kind: string };
}

export const bus = createBus<NexusEvents>();
