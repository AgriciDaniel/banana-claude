'use client';

import { useEffect } from 'react';
import { getAssistant } from '@/ai/AssistantEngine';
import { useAssistantStore } from '@/stores/useAssistantStore';

/**
 * Keyboard access to the assistant.
 *
 * A separate listener from Phase 1's, deliberately: the two never contend
 * (`N` is unused there, and Escape is only claimed here while the assistant is
 * actually awake), and keeping them apart means the assistant can be removed
 * without unpicking the OS's own shortcuts.
 *
 * This also gives a wake path to anyone with no microphone and no camera.
 */
export function useAssistantShortcuts() {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      // Never steal keys from the assistant's own text field.
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.isContentEditable)) {
        if (event.key === 'Escape') target.blur();
        return;
      }

      const store = useAssistantStore.getState();

      if (event.key === 'n' || event.key === 'N') {
        event.preventDefault();
        if (store.awake) getAssistant().sleep('manual');
        else getAssistant().wake('manual');
        return;
      }

      if (event.key === 'Escape' && store.awake) {
        // Interrupt first; a second press dismisses. Escape during speech
        // should silence, not close.
        if (store.status === 'speaking' || store.status === 'streaming') {
          getAssistant().interrupt();
        } else {
          getAssistant().sleep('manual');
        }
      }
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
