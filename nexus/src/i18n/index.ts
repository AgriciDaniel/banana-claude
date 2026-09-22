'use client';

import { create } from 'zustand';
import { en, type TranslationKey } from './en';
import { fr } from './fr';

export type Locale = 'en' | 'fr';

export interface LocaleMeta {
  code: Locale;
  /** Shown in the switch. Always in the language itself, never translated. */
  label: string;
  /** Two-letter tag for the compact toggle. */
  short: string;
  /** BCP-47 tag for `<html lang>` and Intl formatting. */
  tag: string;
}

export const LOCALES: LocaleMeta[] = [
  { code: 'en', label: 'English', short: 'EN', tag: 'en' },
  { code: 'fr', label: 'Français', short: 'FR', tag: 'fr' },
];

/**
 * The document title is rendered on the server in English, so it is the one
 * string the catalogue cannot reach. Updated imperatively instead — the tab
 * label is part of the interface and should not stay in the wrong language.
 */
const TITLES: Record<Locale, string> = {
  en: 'NEXUS — Spatial Computing Environment',
  fr: 'NEXUS — Environnement de calcul spatial',
};

function applyDocumentLocale(locale: Locale) {
  document.documentElement.lang = locale;
  document.title = TITLES[locale];
}

const CATALOGUES: Record<Locale, Record<TranslationKey, string>> = { en, fr };

const STORAGE_KEY = 'nexus.locale';

/** Explicit choice first, then the browser's preference, then English. */
function detectLocale(): Locale {
  if (typeof window === 'undefined') return 'en';
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === 'en' || saved === 'fr') return saved;
  } catch {
    /* private mode / storage disabled — fall through to detection */
  }
  const preferred = navigator.languages ?? [navigator.language];
  for (const lang of preferred) {
    if (typeof lang === 'string' && lang.toLowerCase().startsWith('fr')) return 'fr';
  }
  return 'en';
}

interface LocaleState {
  locale: Locale;
  /** False until detection has run on the client — guards hydration. */
  resolved: boolean;
  setLocale: (locale: Locale) => void;
  resolve: () => void;
}

export const useLocaleStore = create<LocaleState>((set) => ({
  // Always start at the SSR-safe default; detection happens in `resolve()`
  // after mount, so the server and the first client paint agree.
  locale: 'en',
  resolved: false,
  setLocale: (locale) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      /* non-fatal: the choice simply will not persist */
    }
    applyDocumentLocale(locale);
    set({ locale });
  },
  resolve: () => {
    const locale = detectLocale();
    applyDocumentLocale(locale);
    set({ locale, resolved: true });
  },
}));

type Params = Record<string, string | number>;

function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in params ? String(params[key]) : match,
  );
}

/**
 * Imperative translator for non-React callers — the gesture engine, the audio
 * bindings, the quality governor. Reads the current locale off the store, so
 * a log line written during a gesture is in the language selected at that
 * moment without any of those modules knowing i18n exists.
 */
export function t(key: TranslationKey, params?: Params): string {
  const { locale } = useLocaleStore.getState();
  return interpolate(resolveString(locale, key), params);
}

/** locale -> English -> the key itself. Never returns undefined. */
function resolveString(locale: Locale, key: TranslationKey): string {
  return CATALOGUES[locale]?.[key] ?? en[key] ?? key;
}

/** Hook form. Subscribes, so components re-render when the locale changes. */
export function useT(): (key: TranslationKey, params?: Params) => string {
  const locale = useLocaleStore((s) => s.locale);
  return (key, params) => interpolate(resolveString(locale, key), params);
}

/** Current BCP-47 tag, for Intl date/number formatting. */
export function useLocaleTag(): string {
  const locale = useLocaleStore((s) => s.locale);
  return LOCALES.find((l) => l.code === locale)?.tag ?? 'en';
}

export type { TranslationKey };
