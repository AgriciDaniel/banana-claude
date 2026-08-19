/**
 * Verifies an Instagram token before NEXUS ever tries to use it.
 *
 * Written because the failure modes here are all silent and all look alike: a
 * personal account authenticates perfectly and simply returns nothing, an
 * expired token looks like a wrong token, and a Route B token used without a
 * linked Page fails with a message about permissions rather than about Pages.
 * Each of those gets a distinct, actionable answer here.
 *
 *   node scripts/instagram-check.mjs
 */

import { readFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

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
    /* no .env.local yet — env vars may still be set another way */
  }
}

const ok = (m) => console.log(`  \u2713 ${m}`);
const bad = (m) => console.log(`  \u2717 ${m}`);
const note = (m) => console.log(`    ${m}`);

await loadEnv();

const token = process.env.INSTAGRAM_TOKEN ?? process.env.IG_GRAPH_TOKEN;
const userId = process.env.INSTAGRAM_USER_ID;

console.log('\nNEXUS \u00b7 Instagram check\n');

if (!token) {
  bad('No token found.');
  note('Set IG_GRAPH_TOKEN in nexus/.env.local (INSTAGRAM_TOKEN also works).');
  note('');
  note('To get one, on a Professional or Creator account:');
  note('  1. developers.facebook.com  \u2192  create an app');
  note('  2. add the "Instagram" product  \u2192  "Instagram Login"');
  note('  3. generate a long-lived token (about 60 days, then renew)');
  process.exit(1);
}

const usingInstagramLogin = !userId;
const base = usingInstagramLogin ? 'https://graph.instagram.com' : 'https://graph.facebook.com/v21.0';
const me = usingInstagramLogin ? 'me' : userId;

ok(`Token present (${token.length} characters)`);
note(usingInstagramLogin ? 'Route A \u2014 Instagram Login, no Facebook Page needed' : `Route B \u2014 Graph API, user id ${userId}`);

const fields = 'username,account_type,followers_count,follows_count,media_count';
let profile;
try {
  const res = await fetch(`${base}/${me}?fields=${fields}&access_token=${token}`);
  profile = await res.json();
  if (!res.ok) {
    bad(`API returned ${res.status}`);
    note(profile?.error?.message ?? 'no message');
    if (!usingInstagramLogin) {
      note('');
      note('On Route B the account must be linked to a Facebook PAGE.');
      note('Linking Instagram to a personal profile via Accounts Center does not count.');
      note('Unset INSTAGRAM_USER_ID to try Route A instead.');
    }
    process.exit(1);
  }
} catch (error) {
  bad(`Request failed: ${error.message}`);
  process.exit(1);
}

ok(`Authenticated as @${profile.username}`);

if (profile.account_type && profile.account_type === 'PERSONAL') {
  bad('This is a PERSONAL account.');
  note('No API returns statistics for a personal account, whatever the token.');
  note('Instagram app \u2192 Settings \u2192 Account type and tools \u2192 switch to Professional.');
  process.exit(1);
}

ok(`Account type: ${profile.account_type ?? 'not reported'}`);
if (typeof profile.followers_count === 'number') ok(`Followers: ${profile.followers_count}`);
if (typeof profile.media_count === 'number') ok(`Posts: ${profile.media_count}`);

const insights = await fetch(
  `${base}/${me}/insights?metric=reach&period=day&access_token=${token}`,
).then((r) => r.json()).catch(() => null);

if (insights?.data?.length) {
  ok('Insights readable \u2014 the Instagram module will show live data.');
} else {
  bad('Profile readable, but insights are not.');
  note(insights?.error?.message ?? 'no message');
  note('The token likely lacks the insights permission.');
  process.exit(1);
}

console.log('\nReady. Start NEXUS and open the Instagram module.\n');
