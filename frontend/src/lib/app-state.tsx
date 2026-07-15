"use client"

/**
 * App-wide client state:
 *
 *  - FiltersProvider   global store + time-range filters (persisted, shown in
 *                      the top bar, consumed by every page)
 *  - DataProvider      a "data version" counter — bump it and every card
 *                      refetches. Replaces the old full-page reloads.
 *  - JobsProvider      polls /jobs while imports are running, toasts when a
 *                      tracked job lands, and bumps the data version.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { getJobs, type ImportJob } from "@/lib/api"
import { useI18n } from "@/lib/i18n"

// ---------------------------------------------------------------------------
// Time ranges (shared shape with the old TimeRange component)
// ---------------------------------------------------------------------------
export interface Range {
  key: string
  label: string // i18n key for presets; display text for custom months
  start?: string
  end?: string
}

/** Local date -> YYYY-MM-DD (avoids UTC off-by-one from toISOString). */
export function isoDay(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function firstOfMonth(y: number, m: number): string {
  return isoDay(new Date(y, m, 1))
}

export function buildRanges(): Range[] {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  return [
    { key: "all", label: "range.all" },
    { key: "month", label: "range.month", start: firstOfMonth(y, m), end: firstOfMonth(y, m + 1) },
    { key: "last", label: "range.last", start: firstOfMonth(y, m - 1), end: firstOfMonth(y, m) },
    { key: "3m", label: "range.3m", start: firstOfMonth(y, m - 2), end: firstOfMonth(y, m + 1) },
    { key: "year", label: "range.year", start: isoDay(new Date(y, 0, 1)), end: isoDay(new Date(y + 1, 0, 1)) },
  ]
}

export const DEFAULT_RANGE: Range = { key: "all", label: "range.all" }

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------
interface Filters {
  store: string
  setStore: (s: string) => void
  range: Range
  setRange: (r: Range) => void
}

const FiltersContext = createContext<Filters | null>(null)
const FILTER_KEY = "bonfire.filters"

export function FiltersProvider({ children }: { children: React.ReactNode }) {
  const [store, setStoreState] = useState("all")
  const [range, setRangeState] = useState<Range>(DEFAULT_RANGE)

  // Restore after mount (hydration-safe). Custom month ranges are rebuilt
  // from their key so the dates stay correct. localStorage is only readable
  // post-mount, so this one-time sync-in-effect is deliberate.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(FILTER_KEY)
      if (!raw) return
      const saved = JSON.parse(raw) as { store?: string; rangeKey?: string }
      if (saved.store) setStoreState(saved.store)
      if (saved.rangeKey) {
        const preset = buildRanges().find((r) => r.key === saved.rangeKey)
        if (preset) setRangeState(preset)
        else if (saved.rangeKey.startsWith("custom:")) {
          const value = saved.rangeKey.slice("custom:".length)
          const [yy, mm] = value.split("-").map(Number)
          if (yy && mm) {
            setRangeState({
              key: saved.rangeKey,
              label: new Date(yy, mm - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" }),
              start: `${value}-01`,
              end: isoDay(new Date(yy, mm, 1)),
            })
          }
        }
      }
    } catch { /* corrupt storage — keep defaults */ }
  }, [])
  /* eslint-enable react-hooks/set-state-in-effect */

  const persist = (storeVal: string, rangeVal: Range) => {
    try {
      window.localStorage.setItem(FILTER_KEY, JSON.stringify({ store: storeVal, rangeKey: rangeVal.key }))
    } catch { /* private mode */ }
  }

  const setStore = useCallback((s: string) => {
    setStoreState(s)
    setRangeState((r) => { persist(s, r); return r })
  }, [])
  const setRange = useCallback((r: Range) => {
    setRangeState(r)
    setStoreState((s) => { persist(s, r); return s })
  }, [])

  const value = useMemo(() => ({ store, setStore, range, setRange }), [store, range, setStore, setRange])
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>
}

export function useFilters(): Filters {
  const ctx = useContext(FiltersContext)
  if (!ctx) throw new Error("useFilters must be used inside <FiltersProvider>")
  return ctx
}

// ---------------------------------------------------------------------------
// Data version (targeted refresh instead of page reloads)
// ---------------------------------------------------------------------------
interface DataBus {
  version: number
  refresh: () => void
}

const DataContext = createContext<DataBus | null>(null)

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [version, setVersion] = useState(0)
  const refresh = useCallback(() => setVersion((v) => v + 1), [])
  const value = useMemo(() => ({ version, refresh }), [version, refresh])
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}

export function useDataVersion(): DataBus {
  const ctx = useContext(DataContext)
  if (!ctx) throw new Error("useDataVersion must be used inside <DataProvider>")
  return ctx
}

// ---------------------------------------------------------------------------
// Import jobs
// ---------------------------------------------------------------------------
interface JobsState {
  jobs: ImportJob[]
  active: number
  /** Call after triggering an upload/fetch so polling speeds up immediately. */
  nudge: () => void
}

const JobsContext = createContext<JobsState | null>(null)

const FAST_POLL_MS = 2500
const SLOW_POLL_MS = 30000
const NUDGE_WINDOW_MS = 30000

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const { t } = useI18n()
  const { refresh } = useDataVersion()
  const [jobs, setJobs] = useState<ImportJob[]>([])
  const [active, setActive] = useState(0)
  const lastNudge = useRef(0)
  const activeRef = useRef(0)
  const known = useRef<Map<number, string>>(new Map())
  const first = useRef(true)

  const poll = useCallback(async () => {
    try {
      const data = await getJobs(15)
      setJobs(data.jobs)
      setActive(data.active)
      activeRef.current = data.active

      // Announce transitions to a terminal state (skip the very first load —
      // history isn't news).
      if (!first.current) {
        let landed = false
        for (const job of data.jobs) {
          const prev = known.current.get(job.id)
          const terminal = ["done", "duplicate", "needs_review", "failed"].includes(job.status)
          const isNew = prev === undefined
          const changed = prev !== undefined && prev !== job.status
          if (terminal && (changed || (isNew && Date.now() - lastNudge.current < NUDGE_WINDOW_MS))) {
            const msg = job.message || job.filename || `#${job.id}`
            if (job.status === "done") toast.success(t("import.toast.done", { msg }))
            else if (job.status === "needs_review") toast.warning(t("import.toast.needsReview", { msg }))
            else if (job.status === "duplicate") toast.info(t("import.toast.duplicate", { msg }))
            else if (job.status === "failed") toast.error(t("import.toast.failed", { msg: job.error || msg }))
            landed = true
          }
        }
        if (landed) refresh()
      }
      first.current = false
      for (const job of data.jobs) known.current.set(job.id, job.status)
    } catch {
      /* backend momentarily unreachable — next tick retries */
    }
  }, [refresh, t])

  // The loop reads the latest poll() through a ref so the interval doesn't
  // restart every time a locale/refresh change recreates the callback.
  const pollRef = useRef(poll)
  useEffect(() => { pollRef.current = poll }, [poll])

  const nudge = useCallback(() => {
    lastNudge.current = Date.now()
    void pollRef.current()
  }, [])

  useEffect(() => {
    let cancelled = false
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
    const loop = async () => {
      while (!cancelled) {
        await pollRef.current()
        const fast = activeRef.current > 0 || Date.now() - lastNudge.current < NUDGE_WINDOW_MS
        await sleep(fast ? FAST_POLL_MS : SLOW_POLL_MS)
      }
    }
    void loop()
    return () => { cancelled = true }
  }, [])

  const value = useMemo(() => ({ jobs, active, nudge }), [jobs, active, nudge])
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}

export function useJobs(): JobsState {
  const ctx = useContext(JobsContext)
  if (!ctx) throw new Error("useJobs must be used inside <JobsProvider>")
  return ctx
}

// ---------------------------------------------------------------------------
// Small data-fetch helper with loading/error/retry — the standard card state.
// ---------------------------------------------------------------------------
export function useApi<T>(fn: () => Promise<T>, deps: unknown[]): {
  data: T | null
  error: boolean
  loading: boolean
  retry: () => void
  setData: (d: T | null) => void
} {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const seq = useRef(0)

  useEffect(() => {
    // Fetch-in-effect: the only synchronous setState here is the loading
    // flag; results land async and are guarded by seq. Restructuring to
    // appease the rule would just hide the flag behind a microtask.
    /* eslint-disable react-hooks/set-state-in-effect */
    const mySeq = ++seq.current
    setLoading(true)
    setError(false)
    /* eslint-enable react-hooks/set-state-in-effect */
    fn().then((result) => {
      if (mySeq !== seq.current) return
      setData(result)
      setLoading(false)
    }).catch(() => {
      if (mySeq !== seq.current) return
      setError(true)
      setLoading(false)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt])

  const retry = useCallback(() => setAttempt((a) => a + 1), [])
  return { data, error, loading, retry, setData }
}
