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
import type { ChartSpec } from '@/media/types';
import { proposalLines, rememberChart } from './strategyMemory';
import {
  clearMedia,
  generateImage,
  showChart,
  showImage,
  showShape,
  showVideo,
} from '@/media/actions';
import type { ShapeKind } from '@/media/types';
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
    name: 'generate_image',
    description:
      'Create an image from a description and place it in the room. Use when the user asks to see, draw, imagine or picture something that does not already exist. Takes several seconds.',
    parameters: {
      type: 'OBJECT',
      properties: {
        prompt: {
          type: 'STRING',
          description: 'A vivid visual description of the subject. English works best.',
        },
      },
      required: ['prompt'],
    },
  },
  {
    name: 'show_image',
    description:
      'Display an existing image or video already known from a module - an Instagram post, a project asset. Requires a direct media URL, never a page URL.',
    parameters: {
      type: 'OBJECT',
      properties: {
        url: { type: 'STRING', description: 'Direct URL to the image or video file.' },
        title: { type: 'STRING' },
      },
      required: ['url'],
    },
  },
  {
    name: 'show_chart',
    description:
      'Draw a statistic in the room as a chart. Use this whenever you cite figures - a comparison, a trend, a share, a single headline number. Always fill in "source". Set "benchmark" to the reference the user should be measured against, and "note" to the one action you recommend as a result. A chart without a benchmark and a note is only decoration.',
    parameters: {
      type: 'OBJECT',
      properties: {
        kind: {
          type: 'STRING',
          enum: ['bar', 'line', 'donut', 'kpi', 'funnel', 'flow', 'playbook', 'plan', 'profile'],
          description:
            'bar to compare things, line for a trend over time, donut for a breakdown of a whole, kpi for one headline number, funnel for stages losing volume (order the points from widest to narrowest), flow for the steps of a method (labels only, pass value 1), playbook to put what works on other channels beside what we do about it - pass the reference channels as points and the transposition as steps. plan for an action plan: each point is one action, its value is the week it happens in, and "target" says which number should move and how far. profile is the factsheet that belongs beside a photograph: "facts" carries what characterises the subject and "steps" its honours or milestones.',
        },
        title: { type: 'STRING', description: 'The claim the chart makes, in a few words.' },
        source: {
          type: 'STRING',
          description: 'Where the figures came from and when, e.g. "Metricool 2025 study" or "Instagram module, live".',
        },
        unit: { type: 'STRING', description: 'Appended to values: %, K, min, EUR.' },
        points: {
          type: 'ARRAY',
          description:
            'Two to six points. For kpi, exactly one. For flow, up to five steps whose labels are the steps themselves.',
          items: {
            type: 'OBJECT',
            properties: {
              label: { type: 'STRING' },
              value: { type: 'NUMBER' },
              mine: {
                type: 'BOOLEAN',
                description: "True for the user's own figure, so it is highlighted against the rest.",
              },
            },
            required: ['label', 'value'],
          },
        },
        benchmark: { type: 'NUMBER', description: 'Reference value drawn across the plot.' },
        benchmarkLabel: { type: 'STRING', description: 'Two or three words naming the reference.' },
        steps: {
          type: 'ARRAY',
          description:
            'A short list of lines. For playbook, up to four actions on OUR subject derived from the reference points, each concrete enough to start this week. For profile, the honours or milestones: "Coupe du monde 2018", "Ballon d\'Or 2025".',
          items: { type: 'STRING' },
        },
        facts: {
          type: 'ARRAY',
          description:
            'profile only: up to six label/value pairs describing the subject - position, club, age, nationality, height. Values are plain text, not numbers.',
          items: {
            type: 'OBJECT',
            properties: { label: { type: 'STRING' }, value: { type: 'STRING' } },
            required: ['label', 'value'],
          },
        },
        strengths: {
          type: 'ARRAY',
          description:
            'profile only: up to three strong points. This is YOUR reading, not a looked-up fact, and it is drawn below a dividing rule to say so.',
          items: { type: 'STRING' },
        },
        weaknesses: {
          type: 'ARRAY',
          description:
            'profile only: up to three limits or weak points, judged as fairly as the strengths. A profile with only strengths is advertising.',
          items: { type: 'STRING' },
        },
        target: {
          type: 'OBJECT',
          description:
            'plan only: what the plan is meant to move. Required for a plan - without it there is no way to tell later whether it worked.',
          properties: {
            metric: { type: 'STRING', description: 'Name of the number, e.g. "vues par abonne".' },
            from: { type: 'NUMBER', description: 'Where it stands today.' },
            to: { type: 'NUMBER', description: 'Where it should stand at the end.' },
            unit: { type: 'STRING' },
          },
          required: ['metric', 'from', 'to'],
        },
        note: {
          type: 'STRING',
          description:
            'One sentence saying what to DO about what the chart shows. Imperative, concrete, specific to this user.',
        },
      },
      required: ['kind', 'title'],
    },
  },
  {
    name: 'show_video',
    description:
      'Play a clip in the room. Requires a direct video file URL (mp4 or webm), never a page or a watch link.',
    parameters: {
      type: 'OBJECT',
      properties: {
        url: { type: 'STRING', description: 'Direct URL to the video file.' },
        title: { type: 'STRING' },
      },
      required: ['url'],
    },
  },
  {
    name: 'show_shape',
    description:
      'Place a glowing parametric solid in the room. Use for illustrating a form, a comparison of size, or when the user asks for a shape.',
    parameters: {
      type: 'OBJECT',
      properties: {
        shape: {
          type: 'STRING',
          enum: ['sphere', 'box', 'torus', 'knot', 'icosahedron', 'cylinder', 'cone', 'ring'],
        },
        color: { type: 'STRING', description: 'Hex colour such as #63C9FF. Optional.' },
        scale: { type: 'NUMBER', description: '0.3 to 3. Optional.' },
        spin: { type: 'NUMBER', description: 'Turns per second, -2 to 2. Optional.' },
        wireframe: { type: 'BOOLEAN' },
      },
      required: ['shape'],
    },
  },
  {
    name: 'clear_display',
    description: 'Remove whatever is currently displayed in the room.',
    parameters: { type: 'OBJECT', properties: {} },
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

    case 'generate_image': {
      const prompt = String(call.args.prompt ?? '').trim();
      if (!prompt) {
        result = fail('no prompt given');
        break;
      }
      generateImage(prompt);
      // Returns before the image exists: generation takes seconds, and the
      // model should acknowledge rather than wait.
      result = { name: call.name, ok: true, detail: 'image generation started' };
      break;
    }

    case 'show_image': {
      const url = String(call.args.url ?? '').trim();
      if (!/^https?:\/\//i.test(url)) {
        result = fail('a direct http(s) media URL is required');
        break;
      }
      const title = typeof call.args.title === 'string' ? call.args.title : undefined;
      showImage(url, { title });
      result = { name: call.name, ok: true, detail: `displaying ${title ?? url}` };
      break;
    }

    case 'show_chart': {
      const raw = Array.isArray(call.args.points) ? call.args.points : [];
      /*
       * A flow has no quantities -- its points are steps -- so a model that
       * omits `value` there is right, not wrong. Dropping those points left
       * the chart empty and the request silently refused, so the value is
       * supplied instead of demanded.
       */
      // These kinds carry text, not quantities: their points would be dropped
      // by a numeric filter that has nothing to filter.
      const stepsOnly = ['flow', 'playbook', 'plan', 'profile'].includes(String(call.args.kind));
      const points = raw
        .map((p) => p as { label?: unknown; value?: unknown; mine?: unknown })
        .filter((p) => stepsOnly || (typeof p.value === 'number' && Number.isFinite(p.value)))
        .slice(0, 6)
        .map((p) => ({
          label: String(p.label ?? ''),
          value: typeof p.value === 'number' && Number.isFinite(p.value) ? Number(p.value) : 1,
          mine: p.mine === true,
        }));
      /*
       * A profile has no points at all -- its content is `facts` and `steps` --
       * so demanding one silently refused every factsheet the model tried to
       * draw. Each kind is asked for what it actually carries.
       */
      const hasContent =
        points.length > 0 ||
        (call.args.kind === 'profile' &&
          (Array.isArray(call.args.facts) ||
            Array.isArray(call.args.steps) ||
            Array.isArray(call.args.strengths) ||
            Array.isArray(call.args.weaknesses)));

      if (!hasContent) {
        result = fail('a chart needs at least one point with a numeric value');
        break;
      }
      const kind = String(call.args.kind ?? 'bar') as ChartSpec['kind'];
      const spec: ChartSpec = {
        kind: ['bar', 'line', 'donut', 'kpi', 'funnel', 'flow', 'playbook', 'plan', 'profile'].includes(
          kind,
        )
          ? kind
          : 'bar',
        title: String(call.args.title ?? '').slice(0, 90) || 'Sans titre',
        points,
        source: typeof call.args.source === 'string' ? call.args.source.slice(0, 80) : undefined,
        unit: typeof call.args.unit === 'string' ? call.args.unit.slice(0, 8) : undefined,
        benchmark:
          typeof call.args.benchmark === 'number' && Number.isFinite(call.args.benchmark)
            ? call.args.benchmark
            : undefined,
        benchmarkLabel:
          typeof call.args.benchmarkLabel === 'string'
            ? call.args.benchmarkLabel.slice(0, 28)
            : undefined,
        note: typeof call.args.note === 'string' ? call.args.note.slice(0, 160) : undefined,
        target: readTarget(call.args.target),
        facts: readFacts(call.args.facts),
        strengths: readLines(call.args.strengths),
        weaknesses: readLines(call.args.weaknesses),
        steps: Array.isArray(call.args.steps)
          ? call.args.steps.map((x) => String(x).slice(0, 120)).slice(0, 4)
          : undefined,
      };
      showChart(spec);
      // A charted recommendation is a commitment; keep it for next time.
      rememberChart(spec);
      result = { name: call.name, ok: true, detail: `charted ${spec.title}` };
      break;
    }

    case 'show_video': {
      const url = String(call.args.url ?? '').trim();
      if (!/^https?:\/\//i.test(url)) {
        result = fail('a direct http(s) video URL is required');
        break;
      }
      const title = typeof call.args.title === 'string' ? call.args.title : undefined;
      showVideo(url, { title });
      result = { name: call.name, ok: true, detail: `playing ${title ?? url}` };
      break;
    }

    case 'show_shape': {
      const kind = String(call.args.shape ?? '') as ShapeKind;
      const allowed: ShapeKind[] = [
        'sphere', 'box', 'torus', 'knot', 'icosahedron', 'cylinder', 'cone', 'ring',
      ];
      if (!allowed.includes(kind)) {
        result = fail(`unknown shape "${String(call.args.shape)}"`);
        break;
      }
      showShape({
        kind,
        color: typeof call.args.color === 'string' ? call.args.color : undefined,
        scale: typeof call.args.scale === 'number' ? call.args.scale : undefined,
        spin: typeof call.args.spin === 'number' ? call.args.spin : undefined,
        wireframe: call.args.wireframe === true,
      });
      result = { name: call.name, ok: true, detail: `showing a ${kind}` };
      break;
    }

    case 'clear_display': {
      clearMedia();
      result = { name: call.name, ok: true, detail: 'display cleared' };
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
    // Carried on every turn so an analysis can build on the last one rather
    // than starting the same diagnosis over.
    proposals: proposalLines(useLocaleStore.getState().locale),
  };
}

/** A plan's target, kept only when all three parts are actually present. */
function readTarget(raw: unknown): ChartSpec['target'] {
  if (!raw || typeof raw !== 'object') return undefined;
  const t = raw as { metric?: unknown; from?: unknown; to?: unknown; unit?: unknown };
  if (typeof t.metric !== 'string') return undefined;
  if (typeof t.from !== 'number' || !Number.isFinite(t.from)) return undefined;
  if (typeof t.to !== 'number' || !Number.isFinite(t.to)) return undefined;
  return {
    metric: t.metric.slice(0, 60),
    from: t.from,
    to: t.to,
    unit: typeof t.unit === 'string' ? t.unit.slice(0, 8) : undefined,
  };
}

/** A profile's label/value rows, keeping only the pairs that are complete. */
function readFacts(raw: unknown): ChartSpec['facts'] {
  if (!Array.isArray(raw)) return undefined;
  const facts = raw
    .map((entry) => entry as { label?: unknown; value?: unknown })
    .filter((entry) => typeof entry.label === 'string' && typeof entry.value === 'string')
    .slice(0, 6)
    .map((entry) => ({
      label: String(entry.label).slice(0, 30),
      value: String(entry.value).slice(0, 46),
    }));
  return facts.length > 0 ? facts : undefined;
}

/** A short list of plain lines, trimmed to what a panel can hold. */
function readLines(raw: unknown, max = 3): string[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const lines = raw
    .filter((entry) => typeof entry === 'string' && entry.trim().length > 0)
    .slice(0, max)
    .map((entry) => String(entry).slice(0, 110));
  return lines.length > 0 ? lines : undefined;
}
