/**
 * Verifies an Instagram token and works out which API route it can use.
 *
 * Every failure here is silent and they all look alike: a personal account
 * authenticates perfectly and returns nothing, an expired token looks like a
 * wrong token, and a Facebook token on an account linked to a *profile* rather
 * than a *Page* fails with a message about permissions. Each gets a distinct,
 * actionable answer below.
 *
 * It also discovers the Instagram Business account id by itself, which is
 * otherwise the most tedious step of the whole setup: you would have to find
 * the Page, open Graph Explorer and read the id out by hand.
 *
 *   npm run instagram:check
 */

import { readFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

const IG = 'https://graph.instagram.com';
const FB = 'https://graph.facebook.com/v21.0';

const ok = (m) => console.log(`  \u2713 ${m}`);
const bad = (m) => console.log(`  \u2717 ${m}`);
const note = (m) => console.log(`    ${m}`);
const head = (m) => console.log(`\n${m}`);

/** Minimal .env.local reader; dotenv is not a dependency of this project. */
async function loadEnv() {
  try {
    const text = await readFile(join(root, '.env.local'), 'utf8');
    for (const line of text.split(/\r?\n/)) {
      const match = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
      if (!match) continue;
      const [, key, raw] = match;
      if (!process.env[key]) process.env[key] = raw.replace(/^["']|["']$/g, '');
    }
  } catch {
    /* no .env.local yet */
  }
}

async function get(base, path, token) {
  const separator = path.includes('?') ? '&' : '?';
  try {
    const res = await fetch(`${base}/${path}${separator}access_token=${token}`);
    const body = await res.json();
    return { ok: res.ok, status: res.status, body };
  } catch (error) {
    return { ok: false, status: 0, body: { error: { message: error.message } } };
  }
}

await loadEnv();

/** Scopes reported by debug_token, used when explaining a later failure. */
let scopes = [];

const token = process.env.INSTAGRAM_TOKEN ?? process.env.IG_GRAPH_TOKEN;

console.log('\nNEXUS \u00b7 Instagram check');

if (!token) {
  head('No token found.');
  note('Put it in nexus/.env.local as IG_GRAPH_TOKEN (INSTAGRAM_TOKEN also works).');
  note('');
  note('developers.facebook.com \u2192 create an app \u2192 add the Instagram product');
  note('\u2192 generate a long-lived token (~60 days, then renew).');
  note('');
  note('Either token type works. This script figures out which one you have.');
  process.exit(1);
}

/*
 * Recognise an APP token before spending two round trips on it.
 *
 * Its shape is unmistakable — "<numeric app id>|<hash>" — and it is what the
 * Graph API Explorer hands you by default when "User or Page" is left on
 * "App Token". It authenticates the app, not a person, so every /me call fails
 * with "An active access token must be used to query information about the
 * current user". Reported as expiry or missing permissions, that message sends
 * you looking in entirely the wrong place.
 */
if (/^\d+\|/.test(token)) {
  bad('This is an APP token, not a user token.');
  note('Shape "<app id>|<hash>" identifies your app, never a person, so /me');
  note('can never resolve. The Graph API Explorer returns this by default.');
  note('');
  note('Get a user token instead:');
  note('  App Dashboard → Instagram → API setup with Instagram business login');
  note('  → add @your_account → Generate token');
  note('A user token starts with IGQ (Instagram) or EAA (Facebook).');
  note('');
  note('Also: this token embeds a derivative of your app secret.');
  note('Reset it under Settings → Basic → App secret.');
  process.exit(1);
}

ok(`Token present (${token.length} characters)`);

/*
 * Ask Meta what this token actually is before probing endpoints with it.
 *
 * debug_token answers in one call what would otherwise take several guesses:
 * the token type (user, page, system user, app), the scopes actually granted,
 * whether it is still valid, and when it expires. Nearly every confusing
 * failure in this setup is really one of those four facts.
 */
const debug = await get(FB, `debug_token?input_token=${encodeURIComponent(token)}`, token);
const info = debug.body?.data;

if (info) {
  if (info.is_valid === false) {
    bad('Meta reports this token as no longer valid.');
    note('Generate a fresh one and paste it again.');
    process.exit(1);
  }
  const kind = { USER: 'user', PAGE: 'page', SYSTEM_USER: 'system user', APP: 'app' }[info.type] ?? info.type;
  ok(`Type: ${kind}${info.application ? ` · app "${info.application.trim()}"` : ''}`);
  if (info.expires_at) {
    const days = Math.round((info.expires_at * 1000 - Date.now()) / 86400000);
    ok(`Expires in ${days} days`);
  }
  scopes = info.scopes ?? [];
  const wanted = ['instagram_basic', 'instagram_manage_insights'];
  for (const scope of wanted) {
    if (scopes.includes(scope)) ok(`Scope ${scope}`);
    else bad(`Scope ${scope} missing`);
  }
}

// --- Route A: Instagram Login. The token identifies the account directly. ---
head('Route A \u2014 Instagram Login (no Facebook Page needed)');
const a = await get(IG, 'me?fields=username,account_type,followers_count,media_count', token);

let routeA = null;
if (a.ok && a.body.username) {
  ok(`@${a.body.username}${a.body.account_type ? ` \u00b7 ${a.body.account_type}` : ''}`);
  if (a.body.account_type === 'PERSONAL') {
    bad('This account is PERSONAL \u2014 no API returns statistics for it.');
    note('Instagram app \u2192 Settings \u2192 Account type and tools \u2192 switch to Professional.');
    process.exit(1);
  }
  routeA = a.body;
} else {
  bad(a.body?.error?.message ?? `rejected (${a.status})`);
  note('Normal if this is a Facebook token rather than an Instagram one.');
}

// --- Route B: Graph API. Requires a PAGE, and the id can be discovered. -----
head('Route B \u2014 Graph API via Facebook (requires a Page)');
const pages = await get(FB, 'me/accounts?fields=name,instagram_business_account{id,username}', token);

let routeB = null;
if (pages.ok && Array.isArray(pages.body.data)) {
  if (pages.body.data.length === 0) {
    bad('The token sees no Facebook Pages.');
    /*
     * An empty list has two very different causes and the API reports both the
     * same way. Distinguishing them from the granted scopes saves a long hunt
     * through the Business Manager for a Page that was there all along.
     */
    if (!scopes.includes('pages_show_list')) {
      note('Cause: the token lacks pages_show_list, so Pages cannot be listed');
      note('at all. This says nothing about whether a Page exists.');
      note('');
      note('Two ways forward:');
      note('  a) reissue the token with pages_show_list and pages_read_engagement');
      note('  b) skip discovery: set INSTAGRAM_USER_ID by hand, from');
      note('     Business Manager → Accounts → Instagram accounts → your account');
      note('     (the id is shown under the name, as it is for Pages)');
    } else {
      note('This is what "linked to a profile rather than a Page" looks like.');
      note('Linking Instagram to a personal profile via Accounts Center does not count.');
    }
  }
  for (const page of pages.body.data) {
    const linked = page.instagram_business_account;
    if (linked) {
      ok(`Page "${page.name}" \u2192 @${linked.username ?? '?'} (id ${linked.id})`);
      routeB = linked;
    } else {
      note(`Page "${page.name}" has no Instagram account attached`);
    }
  }
} else {
  bad(pages.body?.error?.message ?? `rejected (${pages.status})`);
  note('Normal if this is an Instagram token rather than a Facebook one.');
}

// --- Conclusion -------------------------------------------------------------
head('Result');

if (!routeA && !routeB) {
  bad('Neither route works with this token.');
  note('Most likely the token is expired, or was issued without the');
  note('instagram_basic / instagram_manage_insights permissions.');
  process.exit(1);
}

const base = routeB ? FB : IG;
const target = routeB ? routeB.id : 'me';
const label = routeB ? 'Route B (Graph API)' : 'Route A (Instagram Login)';
ok(`${label} will be used`);

// `reach` is the one account metric that still supports a plain time series;
// `impressions` and `profile_views` were retired in 2025.
const insights = await get(base, `${target}/insights?metric=reach&period=day`, token);
if (insights.ok && insights.body?.data?.length) {
  ok('Insights readable \u2014 the module will show live data.');
} else {
  bad('Profile readable, but insights are not.');
  note(insights.body?.error?.message ?? 'no message');
  note('The token is missing the insights permission.');
  note('Route A needs instagram_business_manage_insights.');
  note('Note: some metrics are unavailable below 100 followers.');
  process.exit(1);
}

head('Put this in nexus/.env.local');
console.log(`\n  IG_GRAPH_TOKEN=<your token>`);
if (routeB) {
  console.log(`  INSTAGRAM_USER_ID=${routeB.id}`);
  note('');
  note('The user id is what selects Route B. Remove it to force Route A.');
} else {
  note('');
  note('No user id: its absence is what selects Route A.');
}
console.log('\nThen start NEXUS and open the Instagram module.\n');
