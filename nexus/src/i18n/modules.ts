import type { ModuleDefinition } from '@/config/modules';
import type { Locale, TranslationKey } from './index';
import { t } from './index';

/**
 * Module text localisation.
 *
 * English lives in `config/modules.ts` alongside the structural data, and is
 * NOT duplicated here — only the French overlay is. Duplicating the English
 * strings into a catalogue would create two places for them to drift apart,
 * and the module registry is the one file a phase-two contributor is certain
 * to edit.
 */

export interface ModuleText {
  name: string;
  descriptor: string;
  metrics: string[];
}

const FR: Record<string, ModuleText> = {
  instagram: {
    name: 'Instagram',
    descriptor: 'Ingestion du graphe social / portée',
    metrics: ['PORTÉE', 'ENGAGE', 'FILE'],
  },
  stocks: {
    name: 'Bourse',
    descriptor: 'Surface de marché / exposition',
    metrics: ['INDICE', 'VOL', 'RISQUE'],
  },
  projects: {
    name: 'Projets',
    descriptor: 'Chantiers actifs / pipeline de build',
    metrics: ['ACTIFS', 'BLOQUÉS', 'VÉLOCITÉ'],
  },
  sports: {
    name: 'Sport',
    descriptor: 'Flux des rencontres / suivi de forme',
    metrics: ['DIRECT', 'CHARGE', 'RÉCUP'],
  },
  calendar: {
    name: 'Agenda',
    descriptor: 'Planification / résolution de conflits',
    metrics: ["AUJOURD'HUI", 'CONFLIT', 'LIBRE'],
  },
  weather: {
    name: 'Météo',
    descriptor: 'Modèle atmosphérique / conditions locales',
    metrics: ['TEMP', 'VENT', 'PRESS'],
  },
  ai: {
    name: 'IA',
    descriptor: 'Noyau de raisonnement / réservé phase deux',
    metrics: ['CTX', 'MODÈLE', 'JETONS'],
  },
  news: {
    name: 'Actualités',
    descriptor: 'Agrégation de fils / filtrage du signal',
    metrics: ['FILS', 'NON LUS', 'BRUIT'],
  },
  music: {
    name: 'Musique',
    descriptor: 'Surface de lecture / analyse spectrale',
    metrics: ['PISTE', 'BPM', 'SORTIE'],
  },
  system: {
    name: 'Système',
    descriptor: 'Diagnostic runtime / pipeline de rendu',
    metrics: ['RENDU', 'THREADS', 'THERMIQUE'],
  },
};

/** Localised name, descriptor and metric labels for one module. */
export function localizeModule(mod: ModuleDefinition, locale: Locale): ModuleText {
  if (locale === 'en') {
    return {
      name: mod.name,
      descriptor: mod.descriptor,
      metrics: mod.metrics.map((m) => m.label),
    };
  }
  const overlay = FR[mod.id];
  if (!overlay) {
    // A module added without a translation still renders — in English, which
    // is a far better failure than a blank card.
    return { name: mod.name, descriptor: mod.descriptor, metrics: mod.metrics.map((m) => m.label) };
  }
  return overlay;
}

/**
 * Metric VALUES are mostly numbers and units, which need no translation. The
 * handful that are words are routed through the catalogue by convention:
 * "GOOD" becomes `word.GOOD`. Anything without a matching key passes straight
 * through, so adding "48.2K" never requires touching a locale file.
 */
export function localizeValue(value: string): string {
  const key = `word.${value}` as TranslationKey;
  const translated = t(key);
  // `t` falls back to the English catalogue and then to the key itself.
  return translated === key ? value : translated;
}
