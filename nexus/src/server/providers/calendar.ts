import type { CalendarData, CalendarEvent, ModuleFeed } from '@/modules/types';

/**
 * Calendar, from an iCalendar feed.
 *
 * ICS rather than the Google Calendar API deliberately: OAuth would need a
 * consent screen, a client secret and a redirect flow for a single-user
 * environment, whereas every calendar worth syncing already publishes a secret
 * ICS URL. Google: Settings -> your calendar -> "Secret address in iCal format".
 *
 * Treat that URL as a password; it is read-only but unauthenticated.
 */

const FOLD = /\r?\n[ \t]/g;

function unfold(text: string): string[] {
  return text.replace(FOLD, '').split(/\r?\n/);
}

/** ICS dates are either 20260819T173000Z, 20260819T173000 or 20260819. */
function parseDate(value: string): { at: number; allDay: boolean } | null {
  const clean = value.trim();
  const dateOnly = /^(\d{4})(\d{2})(\d{2})$/.exec(clean);
  if (dateOnly) {
    const [, y, m, d] = dateOnly;
    return { at: new Date(Number(y), Number(m) - 1, Number(d)).getTime(), allDay: true };
  }
  const full = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(Z)?$/.exec(clean);
  if (!full) return null;
  const [, y, m, d, hh, mm, ss, z] = full;
  const parts = [Number(y), Number(m) - 1, Number(d), Number(hh), Number(mm), Number(ss)] as const;
  const at = z
    ? Date.UTC(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5])
    : new Date(parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]).getTime();
  return { at, allDay: false };
}

/**
 * ICS escapes commas, semicolons, newlines and backslashes with a leading
 * backslash. Written with split/join and a named constant rather than regex
 * literals: escape sequences in this file have been mangled by tooling once
 * already, and there is no way to misread String.fromCharCode(92).
 */
const BACKSLASH = String.fromCharCode(92);

const unescape = (v: string): string =>
  v
    .split(BACKSLASH + 'n')
    .join(' ')
    .split(BACKSLASH + 'N')
    .join(' ')
    .split(BACKSLASH + ',')
    .join(',')
    .split(BACKSLASH + ';')
    .join(';')
    .split(BACKSLASH + BACKSLASH)
    .join(BACKSLASH)
    .trim();

function parseIcs(text: string): CalendarEvent[] {
  const events: CalendarEvent[] = [];
  let current: Partial<CalendarEvent> & { allDay?: boolean } | null = null;

  for (const line of unfold(text)) {
    if (line.startsWith('BEGIN:VEVENT')) {
      current = {};
      continue;
    }
    if (line.startsWith('END:VEVENT')) {
      if (current?.title && current.start) {
        events.push({
          id: current.id ?? `${current.start}-${current.title}`,
          title: current.title,
          start: current.start,
          end: current.end ?? current.start + 3600_000,
          allDay: current.allDay ?? false,
          location: current.location,
        });
      }
      current = null;
      continue;
    }
    if (!current) continue;

    const colon = line.indexOf(':');
    if (colon === -1) continue;
    const name = line.slice(0, colon).split(';')[0]!.toUpperCase();
    const value = line.slice(colon + 1);

    if (name === 'SUMMARY') current.title = unescape(value);
    else if (name === 'UID') current.id = value.trim();
    else if (name === 'LOCATION') current.location = unescape(value);
    else if (name === 'DTSTART') {
      const parsed = parseDate(value);
      if (parsed) {
        current.start = parsed.at;
        current.allDay = parsed.allDay;
      }
    } else if (name === 'DTEND') {
      const parsed = parseDate(value);
      if (parsed) current.end = parsed.at;
    }
  }
  return events;
}

export async function fetchCalendar(
  _params: URLSearchParams,
  signal: AbortSignal,
): Promise<ModuleFeed<CalendarData>> {
  const url = process.env.NEXUS_ICS_URL;
  if (!url) {
    return {
      status: 'unconfigured',
      data: null,
      error: null,
      fetchedAt: Date.now(),
      source: 'iCalendar',
      setupHint:
        'Set NEXUS_ICS_URL to your calendar\u2019s secret iCal address. In Google Calendar: Settings, pick the calendar, then "Secret address in iCal format".',
    };
  }

  const response = await fetch(url, { signal, next: { revalidate: 300 } });
  if (!response.ok) throw new Error(`Calendar feed returned ${response.status}`);

  const now = Date.now();
  const horizon = now + 14 * 86400_000;
  const events = parseIcs(await response.text())
    .filter((e) => e.end >= now - 3600_000 && e.start <= horizon)
    .sort((a, b) => a.start - b.start)
    .slice(0, 40);

  const startOfDay = new Date();
  startOfDay.setHours(0, 0, 0, 0);
  const endOfDay = startOfDay.getTime() + 86400_000;
  const today = events.filter((e) => e.start < endOfDay && e.end > startOfDay.getTime());

  // A conflict is any pair of today's timed events that overlap.
  let conflicts = 0;
  const timed = today.filter((e) => !e.allDay);
  for (let i = 0; i < timed.length; i++) {
    for (let j = i + 1; j < timed.length; j++) {
      if (timed[i]!.start < timed[j]!.end && timed[j]!.start < timed[i]!.end) conflicts++;
    }
  }

  // Unbooked minutes between now and 18:00.
  const workEnd = new Date();
  workEnd.setHours(18, 0, 0, 0);
  let free = Math.max(0, workEnd.getTime() - now);
  for (const event of timed) {
    const overlap = Math.min(event.end, workEnd.getTime()) - Math.max(event.start, now);
    if (overlap > 0) free -= overlap;
  }

  return {
    status: 'live',
    error: null,
    fetchedAt: now,
    source: 'iCalendar',
    data: {
      events,
      todayCount: today.length,
      conflicts,
      freeMinutes: Math.max(0, Math.round(free / 60000)),
    },
  };
}
