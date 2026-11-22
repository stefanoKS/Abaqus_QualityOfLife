import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ja, type Dictionary, type TranslationKey } from './ja'
import { en } from './en'

export type Language = 'ja' | 'en'
export type Vars = Record<string, string | number | undefined | null>

export const LANGUAGES: { id: Language; labelKey: TranslationKey }[] = [
  { id: 'ja', labelKey: 'lang.ja' },
  { id: 'en', labelKey: 'lang.en' },
]

const STORAGE_KEY = 'abaqus-qol.language'
const DEFAULT_LANGUAGE: Language = 'ja'
const dictionaries: Record<Language, Dictionary> = { ja, en }
const locales: Record<Language, string> = { ja: 'ja-JP', en: 'en-US' }

function stored(): Language {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'ja' || value === 'en') return value
  } catch {
    // Private-mode browsers can deny localStorage; the Japanese default still applies.
  }
  // Deliberately ignores navigator.language: the default interface language is Japanese.
  return DEFAULT_LANGUAGE
}

export function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    vars[name] === undefined || vars[name] === null ? match : String(vars[name]),
  )
}

export type Translate = (key: TranslationKey, vars?: Vars) => string

interface I18nValue {
  lang: Language
  locale: string
  t: Translate
  setLang: (lang: Language) => void
  formatDate: (seconds: number) => string
  formatDateTime: (seconds: number) => string
  formatNumber: (value: number, digits?: number) => string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLanguage] = useState<Language>(stored)
  useEffect(() => {
    document.documentElement.lang = lang
    try {
      localStorage.setItem(STORAGE_KEY, lang)
    } catch {
      // Persistence is best-effort; the in-memory selection still works.
    }
  }, [lang])
  const setLang = useCallback((next: Language) => setLanguage(next), [])
  const value = useMemo<I18nValue>(() => {
    const dict = dictionaries[lang]
    return {
      lang,
      locale: locales[lang],
      t: (key, vars) => interpolate(dict[key] ?? ja[key] ?? key, vars),
      setLang,
      formatDate: (seconds) =>
        new Date(seconds * 1000).toLocaleString(locales[lang], {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        }),
      // Runs of the same name are distinguished by ID and by a timestamp with
      // seconds, never by display name alone.
      formatDateTime: (seconds) =>
        new Date(seconds * 1000).toLocaleString(locales[lang], {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        }),
      formatNumber: (number, digits = 3) =>
        number.toLocaleString(locales[lang], {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        }),
    }
  }, [lang, setLang])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}

export function useTranslate(): Translate {
  return useI18n().t
}

/**
 * Translates a backend value that is part of a known vocabulary (job status,
 * worker phase, run mode) and falls back to the raw machine value so a new
 * backend state is still visible instead of being hidden.
 */
export function labelFrom(t: Translate, prefix: 'state' | 'phase' | 'mode', value: string): string {
  const key = (prefix + '.' + value) as TranslationKey
  const dict = ja as Record<string, string>
  return dict[key] === undefined ? value : t(key)
}

export type { TranslationKey }
export { ja, en }
