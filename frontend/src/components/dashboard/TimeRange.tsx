"use client"

import { useMemo } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export interface Range {
  key: string
  label: string
  start?: string
  end?: string
}

/** Local date -> YYYY-MM-DD (avoids UTC off-by-one from toISOString). */
function iso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

/** First day of month (y, m); m may overflow/underflow and JS normalizes it. */
function firstOfMonth(y: number, m: number): string {
  return iso(new Date(y, m, 1))
}

/** Preset ranges, computed relative to today (end is exclusive). */
export function buildRanges(): Range[] {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  return [
    { key: "all", label: "All time" },
    { key: "month", label: "This month", start: firstOfMonth(y, m), end: firstOfMonth(y, m + 1) },
    { key: "last", label: "Last month", start: firstOfMonth(y, m - 1), end: firstOfMonth(y, m) },
    { key: "3m", label: "3 months", start: firstOfMonth(y, m - 2), end: firstOfMonth(y, m + 1) },
    { key: "year", label: "This year", start: iso(new Date(y, 0, 1)), end: iso(new Date(y + 1, 0, 1)) },
  ]
}

/** The last `count` months as { value: "YYYY-MM", label: "Mon YYYY" }, newest first. */
function recentMonths(count = 24): { value: string; label: string }[] {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(y, m - i, 1)
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
    const label = d.toLocaleDateString(undefined, { month: "short", year: "numeric" })
    return { value, label }
  })
}

export const DEFAULT_RANGE: Range = { key: "all", label: "All time" }

export function TimeRange({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const ranges = useMemo(() => buildRanges(), [])
  const months = useMemo(() => recentMonths(24), [])
  const monthValue = value.key.startsWith("custom:") ? value.key.slice("custom:".length) : ""

  const pickMonth = (v: string) => {
    const [yy, mm] = v.split("-").map(Number)
    onChange({
      key: `custom:${v}`,
      label: new Date(yy, mm - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" }),
      start: `${v}-01`,
      end: iso(new Date(yy, mm, 1)), // mm (1-based) as JS month index = first of next month
    })
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded-lg border border-primary/20 bg-secondary/40 p-1">
      {ranges.map((r) => {
        const active = value.key === r.key
        return (
          <button
            key={r.key}
            type="button"
            onClick={() => onChange(r)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium tracking-wide transition-colors ${
              active
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
            }`}
          >
            {r.label}
          </button>
        )
      })}

      <Select value={monthValue || undefined} onValueChange={pickMonth}>
        <SelectTrigger
          className={`h-7 w-[130px] border-none text-xs shadow-none focus:ring-0 focus:ring-offset-0 ${
            monthValue ? "bg-primary/15 text-primary" : "bg-transparent text-muted-foreground hover:bg-secondary/70"
          }`}
        >
          <SelectValue placeholder="Pick month…" />
        </SelectTrigger>
        <SelectContent className="max-h-[300px]">
          {months.map((mo) => (
            <SelectItem key={mo.value} value={mo.value} className="text-xs">
              {mo.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
