"use client"

/**
 * Lightweight i18n: flat key → string dictionaries (en/de), locale-aware
 * date/number formatting via Intl, persisted locale choice.
 *
 * No library: the app has two languages and a few hundred strings; a context
 * plus `t()` keeps the bundle small and the usage greppable.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import { en } from "./en"
import { de } from "./de"

export type Locale = "en" | "de"
const DICTIONARIES: Record<Locale, Record<string, string>> = { en, de }
const STORAGE_KEY = "bonfire.locale"

function detectLocale(): Locale {
  if (typeof window === "undefined") return "en"
  const saved = window.localStorage.getItem(STORAGE_KEY)
  if (saved === "en" || saved === "de") return saved
  return navigator.language?.toLowerCase().startsWith("de") ? "de" : "en"
}

interface I18n {
  locale: Locale
  setLocale: (l: Locale) => void
  /** Translate a key; `{name}` placeholders are filled from vars. */
  t: (key: string, vars?: Record<string, string | number>) => string
  fmtMoney: (n: number) => string
  fmtNumber: (n: number, digits?: number) => string
  fmtDate: (iso: string | Date, style?: "short" | "medium" | "long" | "datetime" | "weekday" | "month") => string
}

const I18nContext = createContext<I18n | null>(null)

export function I18nProvider({ children }: { children: React.ReactNode }) {
  // Start with "en" on both server and first client render (hydration-safe),
  // then adopt the saved/browser locale. localStorage can only be read after
  // mount, so this one-time sync-in-effect is deliberate.
  const [locale, setLocaleState] = useState<Locale>("en")
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setLocaleState(detectLocale()), [])

  // Keep the document language honest for screen readers / translators.
  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    try { window.localStorage.setItem(STORAGE_KEY, l) } catch { /* private mode */ }
  }, [])

  const value = useMemo<I18n>(() => {
    const dict = DICTIONARIES[locale]
    const intlLocale = locale === "de" ? "de-DE" : "en-GB"
    const money = new Intl.NumberFormat(intlLocale, { style: "currency", currency: "EUR" })

    const t = (key: string, vars?: Record<string, string | number>) => {
      let s = dict[key] ?? DICTIONARIES.en[key]
      if (s === undefined) {
        if (process.env.NODE_ENV !== "production") console.warn(`[i18n] missing key: ${key}`)
        return key
      }
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v))
      return s
    }

    const fmtDate: I18n["fmtDate"] = (iso, style = "medium") => {
      const d = typeof iso === "string" ? new Date(iso) : iso
      if (Number.isNaN(d.getTime())) return String(iso)
      const opts: Intl.DateTimeFormatOptions =
        style === "short" ? { day: "2-digit", month: "2-digit", year: "2-digit" }
        : style === "long" ? { day: "numeric", month: "long", year: "numeric" }
        : style === "datetime" ? { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
        : style === "weekday" ? { weekday: "short", day: "numeric", month: "short", year: "numeric" }
        : style === "month" ? { month: "short", year: "numeric" }
        : { day: "2-digit", month: "2-digit", year: "numeric" }
      return new Intl.DateTimeFormat(intlLocale, opts).format(d)
    }

    return {
      locale,
      setLocale,
      t,
      fmtMoney: (n) => money.format(n),
      fmtNumber: (n, digits = 0) =>
        new Intl.NumberFormat(intlLocale, { maximumFractionDigits: digits }).format(n),
      fmtDate,
    }
  }, [locale, setLocale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>")
  return ctx
}
