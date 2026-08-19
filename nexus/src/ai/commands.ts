import { MODULES } from '@/config/modules';
import { ring } from '@/scene/ringController';
import { useCarouselStore } from '@/stores/useCarouselStore';
import { useSystemStore } from '@/stores/useSystemStore';
import { interaction } from '@/stores/runtime';
import { useLocaleStore, type Locale } from '@/i18n';
import { localizeModule } from '@/i18n/modules';
import { getAudio } from '@/audio/AudioEngine';
import { bus } from '@/stores/bus';
import type { CommandCall, CommandResult } from './types';
import { useFeedStore } from '@/modules/store';
import { summariseFeed } from '@/modules/summary';

/**
 * The command engine.
 *
 * The model does not manipulate the scene; it requests one of these verbs, and
 * this file performs it through exactly the same public API a hand gesture
 * uses - `ring.rotate`, `useCarouselStore.expand`, `interaction.frozen`. There
 * is no privileged path for the assistant.
 *
 * That is the reason "open Instagram" and a pinch produce identical motion:
 * they are not two implementations of the same idea, they are one.
 */

/** Function declarations sent to Gemini. Kept small - verbs, not sentences. */
export const COMMAND_DECLARATIONS = [
  {
    name: 'open_module',
    description:
      'Expand a module so its detail surface is visible. Use for "open X", "show X", "bring up X".',
    parameters: {
      type: 'OBJECT',
      properties: {
        module: {
          type: 'STRING',
          description: 'Module id, one of: ' + MODULES.map((m) => m.id).join(', '),
        },
      },
      required: ['module'],
    },
  },
  {
    name: 'focus_module',
    description:
      'Rotate the ring so a module is front and centre, without expanding it. Use for "go to X".',
    parameters: {
      type: 'OBJECT',
      properties: {
        module: { type: 'STRING', description: 'Module id.' },
      },
      required: ['module'],
    },
  },
  {
    name: 'close_module',
    description: 'Collapse the currently expanded module and return it to the ring.',
    parameters: { type: 'OBJECT', properties: {} },
  },
  {
    name: 'rotate_ring',
    description: 'Rotate the carousel by whole slots.',
    parameters: {
      type: 'OBJECT',
      properties: {
        direction: { type: 'STRING', enum: ['left', 'right'] },
        steps: { type: 'NUMBER', description: 'Number of slots, 1 to 5. Defaults to 1.' },
      },
      required: ['direction'],
    },
  },
  {
    name: 'set_freeze',
    description: 'Freeze or resume all motion in the environment.',
    parameters: {
      type: 'OBJECT',
      properties: { frozen: { type: 'BOOLEAN' } },
      required: ['frozen'],
    },
  },
  {
    name: 'set_language',
    description: 'Switch the interface language. Only English (en) and French (fr) exist.',
    parameters: {
      type: 'OBJECT',
      properties: { locale: { type: 'STRING', enum: ['en', 'fr'] } },
      required: ['locale'],
    },
  },
] as const;

/**
 * Resolve a loose module reference to an id.
 *
 * The model is told to send ids, but speech recognition and translation both
 * leak: a French user saying "ouvre la bourse" plausibly produces "bourse".
 * Matching against ids, English names and French names costs nothing and
 * removes a whole class of failure.
 */
export function resolveModule(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const needle = raw.trim().toLowerCase();
  if (!needle) return null;

  for (const mod of MODULES) {
    if (mod.id === needle || mod.code.toLowerCase() === needle) return mod.id;
  }
  for (const mod of MODULES) {
    const names = [
      mod.name.toLowerCase(),
      localizeModule(mod, 'fr').name.toLowerCase(),
      localizeModule(mod, 'en').name.toLowerCase(),
    ];
    if (names.includes(needle)) return mod.id;
  }
  // Last resort: substring, longest id first so "ai" cannot swallow "calendar".
  const byLength = [...MODULES].sort((a, b) => b.id.length - a.id.length);
  for (const mod of byLength) {
    if (needle.includes(mod.id) || mod.id.includes(needle)) return mod.id;
  }
  return null;
}

/** Execute one model-requested command. Never throws; failures are reported. */
export function executeCommand(call: CommandCall): CommandResult {
  const audio = getAudio();
  const cards = useCarouselStore.getState();
  const fail = (detail: string): CommandResult => {
    audio.deny();
    return { name: call.name, ok: false, detail };
  };

  let result: CommandResult;

  switch (call.name) {
    case 'open_module': {
      const id = resolveModule(call.args.module);
      if (!id) {
        result = fail(`unknown module "${String(call.args.module)}"`);
        break;
      }
      const index = MODULES.findIndex((m) => m.id === id);
      // Bring it round first, then expand: expanding a card behind the viewer
      // would put the detail rail beside something nobody can see.
      ring.focus(index);
      cards.expand(id);
      audio.expand();
      result = { name: call.name, ok: true, detail: `expanded ${id}` };
      break;
    }

    case 'focus_module': {
      const id = resolveModule(call.args.module);
      if (!id) {
        result = fail(`unknown module "${String(call.args.module)}"`);
        break;
      }
      if (cards.expandedId && cards.expandedId !== id) cards.collapse();
      ring.focus(MODULES.findIndex((m) => m.id === id));
      cards.select(id);
      audio.confirm();
      result = { name: call.name, ok: true, detail: `focused ${id}` };
      break;
    }

    case 'close_module': {
      if (!cards.expandedId) {
        result = { name: call.name, ok: true, detail: 'nothing was expanded' };
        break;
      }
      const was = cards.expandedId;
      cards.collapse();
      audio.collapse();
      result = { name: call.name, ok: true, detail: `collapsed ${was}` };
      break;
    }

    case 'rotate_ring': {
      const direction = call.args.direction === 'right' ? -1 : 1;
      const raw = Number(call.args.steps ?? 1);
      const steps = Math.max(1, Math.min(5, Number.isFinite(raw) ? Math.round(raw) : 1));
      for (let i = 0; i < steps; i++) ring.rotate(direction as -1 | 1, 1);
      audio.whoosh(direction === 1 ? -1 : 1, 0.9);
      result = {
        name: call.name,
        ok: true,
        detail: `rotated ${call.args.direction} by ${steps}`,
      };
      break;
    }

    case 'set_freeze': {
      const frozen = call.args.frozen !== false;
      interaction.frozen = frozen;
      ring.setLocked(frozen);
      if (frozen) audio.freeze();
      else audio.thaw();
      result = { name: call.name, ok: true, detail: frozen ? 'world frozen' : 'world resumed' };
      break;
    }

    case 'set_language': {
      const locale = call.args.locale === 'fr' ? 'fr' : 'en';
      useLocaleStore.getState().setLocale(locale as Locale);
      audio.tick();
      result = { name: call.name, ok: true, detail: `language ${locale}` };
      break;
    }

    default:
      result = fail(`unknown command "${call.name}"`);
  }

  bus.emit('ai:command', {
    name: call.name,
    argument: typeof call.args.module === 'string' ? call.args.module : null,
    ok: result.ok,
  });
  return result;
}

/** What every module is currently displaying, one line each. */
function readModuleReadings(): string[] {
  const feeds = useFeedStore.getState().feeds;
  return MODULES.map((mod) => summariseFeed(mod.id, feeds[mod.id])).filter(
    (line): line is string => Boolean(line),
  );
}

/** Snapshot of the OS, handed to the model with every turn. */
export function readSceneContext() {
  const cards = useCarouselStore.getState();
  const focusedModule = MODULES[cards.focusedIndex];
  return {
    focused: focusedModule?.id ?? null,
    expanded: cards.expandedId,
    selected: cards.selectedId,
    frozen: interaction.frozen,
    locale: useLocaleStore.getState().locale,
    modules: MODULES.map((m) => m.id),
    localTime: new Date().toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    }),
    quality: useSystemStore.getState().tier,
    readings: readModuleReadings(),
  };
}
