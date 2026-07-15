"use client"

import { useMemo } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { buildRanges, isoDay, type Range } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"

export type { Range }
export { buildRanges, DEFAULT_RANGE } from "@/lib/app-state"

/** The last `count` months as { value: "YYYY-MM", label } (locale-aware), newest first. */
function recentMonths(count: number, fmtDate: (d: Date, s: "month") => string) {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(y, m - i, 1)
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
    return { value, label: fmtDate(d, "month") }
  })
}

export function TimeRange({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  const { t, fmtDate } = useI18n()
  const ranges = useMemo(() => buildRanges(), [])
  const months = useMemo(() => recentMonths(24, fmtDate), [fmtDate])
  const monthValue = value.key.startsWith("custom:") ? value.key.slice("custom:".length) : ""

  const label = (r: Range) => (r.label.startsWith("range.") ? t(r.label) : r.label)

  const pickMonth = (v: string) => {
    const [yy, mm] = v.split("-").map(Number)
    onChange({
      key: `custom:${v}`,
      label: fmtDate(new Date(yy, mm - 1, 1), "month"),
      start: `${v}-01`,
      end: isoDay(new Date(yy, mm, 1)), // mm (1-based) as JS month index = first of next month
    })
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded-lg border border-primary/20 bg-secondary/40 p-1" role="group" aria-label={t("common.date")}>
      {ranges.map((r) => {
        const active = value.key === r.key
        return (
          <button
            key={r.key}
            type="button"
            onClick={() => onChange(r)}
            aria-pressed={active}
            className={`rounded-md px-2.5 py-1 text-xs font-medium tracking-wide transition-colors ${
              active
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
            }`}
          >
            {label(r)}
          </button>
        )
      })}

      <Select value={monthValue || undefined} onValueChange={pickMonth}>
        <SelectTrigger
          aria-label={t("range.pickMonth")}
          className={`h-7 w-[130px] border-none text-xs shadow-none focus:ring-0 focus:ring-offset-0 ${
            monthValue ? "bg-primary/15 text-primary" : "bg-transparent text-muted-foreground hover:bg-secondary/70"
          }`}
        >
          <SelectValue placeholder={t("range.pickMonth")} />
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
