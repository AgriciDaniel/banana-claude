import { scanChannels } from './providers/youtube';

/**
 * Tools the SERVER runs, as distinct from commands the interface performs.
 *
 * Everything in `commands.ts` is one-way: the model asks for a card to open or
 * a chart to appear, the route forwards it to the browser, and the only thing
 * it can honestly report back is that the request was delivered. That is fine
 * for driving an interface and useless for gathering evidence.
 *
 * These are the other kind. They execute here, and their real output goes back
 * into the conversation as a function response, so the model can reason about
 * figures it did not invent. That is what makes a benchmark a measurement
 * rather than a recollection.
 */

export interface ServerToolResult {
  ok: boolean;
  [key: string]: unknown;
}

export const SERVER_TOOL_DECLARATIONS = [
  {
    name: 'scan_channels',
    description:
      "Survey the YouTube channels working a theme and return their real figures. Use this before advising on channel strategy: it is how you find what actually performs in a niche instead of recalling generic advice. Results are sorted by views per subscriber, which is the figure that identifies a channel reaching beyond its existing audience - subscriber count alone only identifies channels that are old. Costs real API quota, so call it once per theme, not once per question.",
    parameters: {
      type: 'OBJECT',
      properties: {
        theme: {
          type: 'STRING',
          description:
            'The subject to survey, in the language the audience speaks. Be specific: "documentaire histoire francophone" finds a niche, "histoire" finds broadcasters.',
        },
        limit: {
          type: 'NUMBER',
          description: 'How many channels to return, 3 to 8. Default 6.',
        },
      },
      required: ['theme'],
    },
  },
] as const;

export function isServerTool(name: string): boolean {
  return SERVER_TOOL_DECLARATIONS.some((tool) => tool.name === name);
}

export async function runServerTool(
  name: string,
  args: Record<string, unknown>,
  signal: AbortSignal,
): Promise<ServerToolResult> {
  try {
    if (name === 'scan_channels') {
      const theme = String(args.theme ?? '').trim();
      const rawLimit = Number(args.limit);
      const limit = Number.isFinite(rawLimit) ? Math.min(8, Math.max(3, rawLimit)) : 6;
      const channels = await scanChannels(theme, signal, limit);

      if (channels.length === 0) {
        return {
          ok: true,
          theme,
          channels: [],
          note: 'No channel above the noise floor was found for this theme. Say so and ask for a narrower or differently worded theme rather than inventing comparisons.',
        };
      }

      return {
        ok: true,
        theme,
        /*
         * Rounded and renamed on the way out. The model reads these figures
         * aloud and charts them, so they arrive in the shape they should be
         * quoted in rather than as raw API fields.
         */
        channels: channels.map((c) => ({
          name: c.title,
          handle: c.handle,
          subscribers: c.subscribers,
          recentAverageViews: c.recentAverage,
          viewsPerSubscriber: Number(c.viewsPerSubscriber.toFixed(2)),
          shortsShare: Math.round(c.shortsShare * 100),
          typicalLengthSeconds: c.medianSeconds,
          bestRecentTitles: c.topTitles,
        })),
        howToRead:
          'viewsPerSubscriber above 0.2 means the channel reaches past its own audience. typicalLengthSeconds and shortsShare describe the format that is working. bestRecentTitles are the actual patterns to study - quote them. Two caveats you must respect: a Short counts a view every time it starts or replays, so view figures from a channel with a high shortsShare are not comparable like-for-like with a long-form channel and you should say so rather than ranking them together silently; and subscriber counts are rounded to three significant figures at source, so treat small differences in the ratio as noise.',
      };
    }

    return { ok: false, error: `unknown server tool: ${name}` };
  } catch (error) {
    /*
     * Errors are returned rather than thrown. A failed scan should let the
     * model say "I could not measure this, here is what is missing" instead of
     * collapsing the whole turn into a stack trace the user never sees.
     */
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
