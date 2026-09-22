import type { ChartSpec } from '@/media/types';

/**
 * What was proposed, and what the numbers were when it was proposed.
 *
 * Without this the assistant restarts from zero every session: it re-measures
 * the same figure, rediscovers the same gap, and proposes the same thing in
 * slightly different words. Advice that cannot remember itself is not a
 * strategy, it is a series of opinions.
 *
 * Every chart carrying a recommendation is recorded here with the figure it
 * was arguing about. Later sessions get that list back, which lets the model
 * do the two things it otherwise cannot: avoid repeating a proposal that is
 * still outstanding, and say whether the number moved since it was made.
 *
 * Deliberately small and local. It lives in localStorage on the user's own
 * machine, holds a couple of dozen entries, and never leaves except as a few
 * lines of context in the next prompt.
 */

export interface Proposal {
  /** Epoch ms. Rendered as an absolute date in the prompt, never "3 days ago". */
  at: number;
  /** The claim the chart was making. */
  subject: string;
  /** The recommendation itself. */
  action: string;
  /** The figure under discussion, if the chart carried one. */
  metric?: { label: string; value: number; unit?: string };
  /** What it was being measured against. */
  benchmark?: { value: number; label?: string };
  source?: string;
  /** A plan's actions, so a later session can ask where they got to. */
  steps?: string[];
  /** What the plan was meant to move, and how far. */
  target?: { metric: string; from: number; to: number; unit?: string };
}

const KEY = 'nexus.strategy.proposals';
const LIMIT = 24;

let cache: Proposal[] | null = null;

function read(): Proposal[] {
  if (cache) return cache;
  if (typeof localStorage === 'undefined') return (cache = []);
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as Proposal[]) : [];
    cache = Array.isArray(parsed) ? parsed : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(list: Proposal[]): void {
  cache = list;
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // A full quota must not break the conversation it was recording.
  }
}

/**
 * Record a chart's recommendation. Charts without a note are not proposals --
 * they are illustrations - and are ignored.
 */
export function rememberChart(spec: ChartSpec): void {
  if (!spec.note) return;

  /*
   * Only record a figure that is genuinely the user's own. A flow's values are
   * a rendering convenience, a plan's are week numbers, and a playbook's are
   * other people's channels -- filing any of those as "your metric" would put
   * a number in the record that means nothing, and the whole point of the
   * record is that a later session can compare against it.
   */
  const mine =
    spec.points.find((p) => p.mine) ?? (spec.kind === 'kpi' ? spec.points[0] : undefined);

  const entry: Proposal = {
    at: Date.now(),
    subject: spec.title,
    action: spec.note,
    metric: mine ? { label: mine.label, value: mine.value, unit: spec.unit } : undefined,
    benchmark:
      spec.benchmark !== undefined
        ? { value: spec.benchmark, label: spec.benchmarkLabel }
        : undefined,
    source: spec.source,
    steps: spec.steps && spec.steps.length > 0 ? spec.steps.slice(0, 5) : undefined,
    target: spec.target,
  };

  const list = read().filter(
    // One entry per subject: a re-analysis supersedes rather than accumulates,
    // otherwise the prompt fills with six versions of the same advice.
    (p) => p.subject.toLowerCase() !== entry.subject.toLowerCase(),
  );
  list.push(entry);
  write(list.slice(-LIMIT));
}

export function proposals(): Proposal[] {
  return read();
}

export function forgetProposals(): void {
  write([]);
}

/**
 * The lines injected into the system instruction. Absolute dates, the figure
 * as it stood, and the action -- enough for the model to compare against
 * today's readings and say what changed.
 */
export function proposalLines(locale: string, max = 6): string[] {
  const list = read().slice(-max);
  if (list.length === 0) return [];

  return list.map((p) => {
    const when = new Date(p.at).toLocaleDateString(locale === 'fr' ? 'fr-FR' : 'en-GB', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
    const parts = [`${when} - ${p.subject}`];
    if (p.metric) {
      const unit = p.metric.unit ? `${p.metric.unit === '%' ? '%' : ` ${p.metric.unit}`}` : '';
      parts.push(`figure at the time: ${p.metric.label} ${p.metric.value}${unit}`);
    }
    if (p.benchmark) {
      parts.push(`measured against ${p.benchmark.value} (${p.benchmark.label ?? 'reference'})`);
    }
    if (p.target) {
      const unit = p.target.unit ? (p.target.unit === '%' ? '%' : ` ${p.target.unit}`) : '';
      parts.push(
        `the plan aimed to take ${p.target.metric} from ${p.target.from}${unit} to ${p.target.to}${unit}`,
      );
    }
    parts.push(`proposed: ${p.action}`);
    if (p.steps) parts.push(`steps were: ${p.steps.join(' / ')}`);
    return parts.join('; ');
  });
}
