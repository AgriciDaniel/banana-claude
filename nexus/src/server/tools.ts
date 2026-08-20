import { scanChannels } from './providers/youtube';
import { findPhoto } from './photo';
import { findFacts } from './facts';
import { RateLimited } from './wikimedia';
import { STATSBOMB_CREDIT, findMatches, matchPlayerStats } from './statsbomb';

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
  {
    name: 'research_subject',
    description:
      "Look up a subject -- a person, a club, a place, a company, a work -- and get back its photograph AND its structured facts in one call: what it is, the properties that characterise it, and the honours or awards it holds. Everything returned has been fetched from Wikidata and Wikipedia, not recalled, so it can be shown as fact. ALWAYS call this before describing a subject you do not have live module data for. Use the result to fill a show_chart profile.",
    parameters: {
      type: 'OBJECT',
      properties: {
        subject: {
          type: 'STRING',
          description: 'Who or what, named plainly: "Ousmane Dembele", "Stade Velodrome", "Peugeot 3008".',
        },
      },
      required: ['subject'],
    },
  },
  {
    name: 'statsbomb_matches',
    description:
      "Find matches in StatsBomb's free event data and get their ids. This is the only football source here with REAL numbers -- actual shots with StatsBomb's own xG on each -- rather than figures recalled or searched. Coverage is what StatsBomb chose to open: World Cups, Champions League, La Liga, Bundesliga, Copa America, women's competitions and more, but NOT the current season. Use it whenever a question can be answered from a specific match rather than from current form.",
    parameters: {
      type: 'OBJECT',
      properties: {
        team: { type: 'STRING', description: 'Team name, e.g. "Argentina", "Barcelona".' },
        competition: { type: 'STRING', description: 'e.g. "FIFA World Cup", "La Liga".' },
        season: { type: 'STRING', description: 'e.g. "2022", "2018/2019".' },
      },
    },
  },
  {
    name: 'statsbomb_match',
    description:
      "Every player's line from one match, computed from the event data itself: shots, goals, StatsBomb xG, xA, passes, pass accuracy, key passes, progressive passes and carries, duels won. Get the id from statsbomb_matches first. These are measurements, not estimates - chart them and say so.",
    parameters: {
      type: 'OBJECT',
      properties: {
        matchId: { type: 'NUMBER', description: 'From statsbomb_matches.' },
        player: {
          type: 'STRING',
          description: 'Optional: return only lines whose player name contains this.',
        },
      },
      required: ['matchId'],
    },
  },
  {
    name: 'find_photo',
    description:
      "Look up a real photograph of a real subject - a person, a place, a building, a team - and get back a URL that actually exists. ALWAYS use this before show_image for anything you do not already have a link for. Do not compose a Wikimedia address yourself: those paths are content hashes, they cannot be recalled, and a guessed one is a dead link that shows the user an empty frame.",
    parameters: {
      type: 'OBJECT',
      properties: {
        subject: {
          type: 'STRING',
          description: 'Who or what to find, named as plainly as possible: "Ousmane Dembele", "Stade de France".',
        },
      },
      required: ['subject'],
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

    if (name === 'statsbomb_matches') {
      const matches = await findMatches(
        {
          team: typeof args.team === 'string' ? args.team : undefined,
          competition: typeof args.competition === 'string' ? args.competition : undefined,
          season: typeof args.season === 'string' ? args.season : undefined,
        },
        signal,
      );
      if (matches.length === 0) {
        return {
          ok: true,
          matches: [],
          note: 'Nothing in the open data matches that. Coverage is selected competitions, never the current season - say which and offer what is there.',
        };
      }
      return { ok: true, matches, source: STATSBOMB_CREDIT };
    }

    if (name === 'statsbomb_match') {
      const matchId = Number(args.matchId);
      if (!Number.isFinite(matchId)) return { ok: false, error: 'a numeric matchId is required' };

      const result = await matchPlayerStats(matchId, signal);
      if (!result) return { ok: false, error: `No event data for match ${matchId}` };

      const wanted = typeof args.player === 'string' ? args.player.toLowerCase() : null;
      const players = wanted
        ? result.players.filter((p) => p.player.toLowerCase().includes(wanted))
        : result.players.slice(0, 14);

      return {
        ok: true,
        matchId,
        players,
        source: STATSBOMB_CREDIT,
        note: "These are measured from the match events, not modelled by you: xg is the figure StatsBomb attached to each shot, and xa is the expected value of the shots each pass created. Cite the source - attribution is a licence condition, and the data is non-commercial.",
      };
    }

    if (name === 'research_subject') {
      const subject = String(args.subject ?? '').trim();
      /*
       * Photograph and facts are fetched together because they are always
       * wanted together, and because two separate tool calls cost two round
       * trips through the model for one question.
       */
      let throttled = false;
      const remember = (error: unknown) => {
        if (error instanceof RateLimited) throttled = true;
        return null;
      };
      const [photo, facts] = await Promise.all([
        findPhoto(subject, signal).catch(remember),
        findFacts(subject, signal).catch(remember),
      ]);

      if (!photo && !facts) {
        /*
         * Being throttled is not the same as finding nothing, and the model
         * will say one or the other aloud. Wikimedia limits hard enough that
         * a few lookups in a row can trip it, so the two are kept apart.
         */
        if (throttled) {
          return {
            ok: false,
            error: 'Wikipedia is rate limiting us right now. Say the lookup is temporarily unavailable and offer to try again in a moment - do NOT say the subject was not found.',
          };
        }
        return {
          ok: true,
          found: false,
          note: `Nothing was found for "${subject}". Say so plainly rather than filling the panel from memory.`,
        };
      }

      return {
        ok: true,
        found: true,
        title: facts?.title ?? photo?.title ?? subject,
        what: facts?.description,
        photoUrl: photo?.url,
        facts: facts?.facts ?? [],
        honours: facts?.honours ?? [],
        source: [facts ? 'Wikidata' : null, photo?.source].filter(Boolean).join(' + '),
        note: 'These facts were fetched, not remembered: show them as they are and cite the source. Anything you add beyond them -- strengths, weaknesses, form, an opinion -- is YOUR reading and must be presented as such, never mixed into the fact list.',
      };
    }

    if (name === 'find_photo') {
      const subject = String(args.subject ?? '').trim();
      const found = await findPhoto(subject, signal);
      if (!found) {
        return {
          ok: true,
          found: false,
          note: `No photograph was found for "${subject}". Say so plainly rather than composing a URL.`,
        };
      }
      return {
        ok: true,
        found: true,
        url: found.url,
        title: found.title,
        description: found.description,
        source: found.source,
        note: 'Pass this url to show_image unchanged. It has been looked up, not guessed.',
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
