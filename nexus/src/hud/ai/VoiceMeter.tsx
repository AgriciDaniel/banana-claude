'use client';

import { useVoiceLevel } from './useVoiceLevel';

/**
 * Speech level, drawn as a symmetric bar cluster.
 *
 * Symmetric because it is the assistant's voice, not the user's input: an
 * asymmetric meter reads as a recording level, a symmetric one reads as
 * something speaking.
 */
export function VoiceMeter({ active, bars = 13 }: { active: boolean; bars?: number }) {
  const level = useVoiceLevel();

  return (
    <div className="flex h-5 items-center gap-[3px]" aria-hidden>
      {Array.from({ length: bars }, (_, i) => {
        // Centre bars react most; the outer ones only move on loud syllables.
        const distance = Math.abs(i - (bars - 1) / 2) / ((bars - 1) / 2);
        const weight = 1 - distance * 0.72;
        const height = active ? Math.max(2, level * 18 * weight + 2) : 2;
        return (
          <span
            key={i}
            className={`w-[2px] rounded-full transition-[height,background-color] duration-75 ${
              active && level > 0.02 ? 'bg-signal' : 'bg-ghost/35'
            }`}
            style={{ height: `${height}px` }}
          />
        );
      })}
    </div>
  );
}
