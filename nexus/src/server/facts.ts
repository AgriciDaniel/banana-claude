/**
 * Structured facts about a subject, from Wikidata.
 *
 * The profile panel was being filled from the model's memory, which is fine
 * until it is not: an age drifts, a club is a transfer window out of date, and
 * nothing on the panel says which parts were looked up. Wikidata is the
 * queryable half of Wikipedia -- every claim is a typed statement with an
 * identifier -- so the same panel can be built from statements instead of
 * recollection.
 *
 * Deliberately domain-agnostic. The property list below covers people, places,
 * organisations and works, and anything a subject does not have simply does
 * not appear. A footballer yields position and club; a stadium yields capacity
 * and opening date; the code does not know or care which it is looking at.
 */

import { wikiJson as json } from './wikimedia';

const WD = 'https://www.wikidata.org/w/api.php';
const ENTITY = 'https://www.wikidata.org/wiki/Special:EntityData';

export interface SubjectFact {
  label: string;
  value: string;
}

export interface SubjectFacts {
  id: string;
  title: string;
  description?: string;
  facts: SubjectFact[];
  /** Awards, honours, titles -- whatever the subject has been given. */
  honours: string[];
}

/**
 * Properties worth showing, in the order they should be read. French labels
 * because the interface is French; the identifiers are language-neutral.
 */
const PROPERTIES: Array<{ id: string; label: string; kind: 'entity' | 'time' | 'quantity' }> = [
  { id: 'P106', label: 'Profession', kind: 'entity' },
  { id: 'P413', label: 'Poste', kind: 'entity' },
  { id: 'P54', label: 'Club', kind: 'entity' },
  { id: 'P118', label: 'Championnat', kind: 'entity' },
  { id: 'P27', label: 'Nationalité', kind: 'entity' },
  { id: 'P569', label: 'Naissance', kind: 'time' },
  { id: 'P570', label: 'Décès', kind: 'time' },
  { id: 'P2048', label: 'Taille', kind: 'quantity' },
  { id: 'P571', label: 'Fondation', kind: 'time' },
  { id: 'P159', label: 'Siège', kind: 'entity' },
  { id: 'P17', label: 'Pays', kind: 'entity' },
  { id: 'P1083', label: 'Capacité', kind: 'quantity' },
  { id: 'P1082', label: 'Population', kind: 'quantity' },
  { id: 'P170', label: 'Auteur', kind: 'entity' },
  { id: 'P577', label: 'Publication', kind: 'time' },
  { id: 'P176', label: 'Fabricant', kind: 'entity' },
];

/** Awards and honours, which are listed rather than shown as label/value. */
const HONOUR_PROPERTIES = ['P166', 'P2522'];

interface Claim {
  mainsnak?: {
    snaktype?: string;
    datavalue?: {
      type?: string;
      value?:
        | string
        | { id?: string }
        | { time?: string }
        | { amount?: string; unit?: string };
    };
  };
  rank?: string;
  qualifiers?: Record<string, unknown>;
}


/** Find the entity for a name. The first hit is right far more often than not. */
async function resolveEntity(subject: string, signal: AbortSignal): Promise<string | null> {
  for (const lang of ['fr', 'en']) {
    const found = await json<{ search?: Array<{ id?: string }> }>(
      `${WD}?action=wbsearchentities&format=json&limit=1&language=${lang}` +
        `&uselang=${lang}&search=${encodeURIComponent(subject)}&origin=*`,
      signal,
    );
    const id = found?.search?.[0]?.id;
    if (id) return id;
  }
  return null;
}

/** Resolve a batch of entity ids to readable labels in one request. */
async function labelsFor(ids: string[], signal: AbortSignal): Promise<Map<string, string>> {
  const out = new Map<string, string>();
  if (ids.length === 0) return out;

  // The API takes fifty at a time, which is far more than a panel can show.
  const batch = ids.slice(0, 50).join('|');
  const data = await json<{
    entities?: Record<string, { labels?: Record<string, { value?: string }> }>;
  }>(
    `${WD}?action=wbgetentities&format=json&props=labels&languages=fr|en&ids=${batch}&origin=*`,
    signal,
  );

  for (const [id, entity] of Object.entries(data?.entities ?? {})) {
    const label = entity.labels?.fr?.value ?? entity.labels?.en?.value;
    if (label) out.set(id, clean(label));
  }
  return out;
}

/** "+1997-05-15T00:00:00Z" is not something to read out. */
function readableTime(raw: string): string {
  const match = /^[+-](\d{4})-(\d{2})-(\d{2})/.exec(raw);
  if (!match) return raw;
  const [, year, month, day] = match;
  if (month === '00' || day === '00') return year!;
  const date = new Date(`${year}-${month}-${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return year!;
  return date.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });
}

/** Symbols read better than words on a panel: "179 cm", not "179 centimètre". */
const UNIT_SYMBOLS: Record<string, string> = {
  centimètre: 'cm',
  centimetre: 'cm',
  mètre: 'm',
  metre: 'm',
  kilogramme: 'kg',
  kilomètre: 'km',
  kilometre: 'km',
  'mètre carré': 'm²',
  année: 'ans',
  euro: '€',
  'dollar des États-Unis': '$',
};

/**
 * French Wikidata writes gendered occupations as a doublet -- "footballeur ou
 * footballeuse" -- which is correct for a database and wrong on a card. The
 * halves are collapsed only when they are plainly the same word twice, so a
 * genuine alternative such as "chanteur ou acteur" survives intact.
 */
function collapseDoublet(label: string): string {
  const match = /^(.+?) ou (.+)$/.exec(label);
  if (!match) return label;
  const [, left, right] = match;
  let shared = 0;
  while (shared < left!.length && shared < right!.length && left![shared] === right![shared]) {
    shared++;
  }
  return shared >= 5 && shared >= Math.min(left!.length, right!.length) - 3 ? left! : label;
}

/** Wikidata labels carry stray direction marks that show up as gaps. */
function clean(label: string): string {
  return collapseDoublet(label.replace(/[​-‏‪-‮﻿]/g, '').trim());
}

function readableQuantity(amount: string, unitLabel?: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount;
  const rounded = Number.isInteger(value) ? value.toLocaleString('fr-FR') : String(value);
  if (!unitLabel) return rounded;
  const symbol = UNIT_SYMBOLS[unitLabel.toLowerCase()] ?? unitLabel;
  return `${rounded} ${symbol}`;
}

/** Best claim for a property: preferred rank wins, otherwise the first normal one. */
function bestClaims(claims: Claim[] | undefined): Claim[] {
  if (!claims || claims.length === 0) return [];
  const usable = claims.filter((c) => c.mainsnak?.snaktype === 'value' && c.rank !== 'deprecated');
  const preferred = usable.filter((c) => c.rank === 'preferred');
  return preferred.length > 0 ? preferred : usable;
}

export async function findFacts(
  subject: string,
  signal: AbortSignal,
): Promise<SubjectFacts | null> {
  const query = subject.trim();
  if (!query) return null;

  const id = await resolveEntity(query, signal);
  if (!id) return null;

  const data = await json<{
    entities?: Record<
      string,
      {
        labels?: Record<string, { value?: string }>;
        descriptions?: Record<string, { value?: string }>;
        claims?: Record<string, Claim[]>;
      }
    >;
  }>(`${ENTITY}/${id}.json`, signal);

  const entity = data?.entities?.[id];
  if (!entity) return null;

  const claims = entity.claims ?? {};

  /*
   * Two passes. The first collects every entity id that will need a label --
   * values and units alike -- so they can be resolved in ONE request instead
   * of one per fact, which for a footballer would be a dozen round trips.
   */
  const needed = new Set<string>();
  for (const property of PROPERTIES) {
    for (const claim of bestClaims(claims[property.id]).slice(0, 2)) {
      const value = claim.mainsnak?.datavalue?.value;
      if (property.kind === 'entity' && typeof value === 'object' && value && 'id' in value) {
        if (value.id) needed.add(value.id);
      }
      if (property.kind === 'quantity' && typeof value === 'object' && value && 'unit' in value) {
        const unit = (value.unit ?? '').split('/').pop();
        if (unit && unit.startsWith('Q')) needed.add(unit);
      }
    }
  }
  for (const property of HONOUR_PROPERTIES) {
    for (const claim of bestClaims(claims[property]).slice(0, 6)) {
      const value = claim.mainsnak?.datavalue?.value;
      if (typeof value === 'object' && value && 'id' in value && value.id) needed.add(value.id);
    }
  }

  const labels = await labelsFor([...needed], signal);

  const facts: SubjectFact[] = [];
  for (const property of PROPERTIES) {
    const chosen = bestClaims(claims[property.id]).slice(0, 2);
    const values: string[] = [];

    for (const claim of chosen) {
      const value = claim.mainsnak?.datavalue?.value;
      if (value === undefined) continue;

      if (property.kind === 'entity' && typeof value === 'object' && 'id' in value) {
        const label = value.id ? labels.get(value.id) : undefined;
        if (label) values.push(label);
      } else if (property.kind === 'time' && typeof value === 'object' && 'time' in value) {
        if (value.time) values.push(readableTime(value.time));
      } else if (property.kind === 'quantity' && typeof value === 'object' && 'amount' in value) {
        const unit = (value.unit ?? '').split('/').pop();
        const unitLabel = unit && unit.startsWith('Q') ? labels.get(unit) : undefined;
        if (value.amount) values.push(readableQuantity(value.amount, unitLabel));
      }
    }

    if (values.length > 0) facts.push({ label: property.label, value: values.join(', ') });
  }

  const honours: string[] = [];
  for (const property of HONOUR_PROPERTIES) {
    for (const claim of bestClaims(claims[property]).slice(0, 6)) {
      const value = claim.mainsnak?.datavalue?.value;
      if (typeof value === 'object' && value && 'id' in value && value.id) {
        const label = labels.get(value.id);
        if (label && !honours.includes(label)) honours.push(label);
      }
    }
  }

  return {
    id,
    title: entity.labels?.fr?.value ?? entity.labels?.en?.value ?? query,
    description: entity.descriptions?.fr?.value ?? entity.descriptions?.en?.value,
    facts: facts.slice(0, 6),
    honours: honours.slice(0, 6),
  };
}
