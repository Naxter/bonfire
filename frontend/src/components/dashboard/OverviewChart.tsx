"use client"

import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"
import { storeColor } from "@/lib/theme"
import { useChartTheme } from "@/lib/use-chart-theme"
import { useI18n } from "@/lib/i18n"
import type { MonthlyRow } from "@/lib/api"

interface CustomTooltipProps {
  active?: boolean
  payload?: { name: string; value: number; color?: string }[]
  label?: string
  // injected by us (recharts merges its own props into the element)
  monthLabel?: string
  totalLabel?: string
  fmtMoney?: (n: number) => string
}

function SpendingTooltip({ active, payload, label, monthLabel, totalLabel, fmtMoney }: CustomTooltipProps) {
  if (active && payload && payload.length && fmtMoney) {
    const total = payload.reduce((sum, entry) => sum + entry.value, 0)
    return (
      <div className="rounded-lg border border-border bg-popover/95 p-3 shadow-[0_8px_24px_-10px_rgba(0,0,0,0.6)] backdrop-blur min-w-[150px]">
        <div className="flex flex-col mb-2 border-b border-border pb-2">
          <span className="hud-label">{monthLabel}</span>
          <span className="font-bold text-foreground">{label}</span>
        </div>
        <div className="space-y-1.5">
          {payload.map((entry, index) => (
            <div key={index} className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-[2px]" style={{ backgroundColor: entry.color }} />
                <span className="text-xs text-muted-foreground uppercase font-medium tracking-wider">{entry.name}</span>
              </div>
              <span className="font-bold text-sm">{fmtMoney(entry.value)}</span>
            </div>
          ))}
          {payload.length > 1 && (
            <div className="flex items-center justify-between gap-4 pt-1.5 mt-1.5 border-t border-border">
              <span className="text-xs font-bold uppercase text-primary tracking-wider">{totalLabel}</span>
              <span className="font-bold text-sm neon-text">{fmtMoney(total)}</span>
            </div>
          )}
        </div>
      </div>
    )
  }
  return null
}

export function OverviewChart({ data }: { data: MonthlyRow[] }) {
  const chart = useChartTheme()
  const { t, fmtMoney } = useI18n()

  const seriesKeys = Array.from(
    new Set(data.flatMap((row) => Object.keys(row).filter((k) => k !== "month")))
  )
  const colorFor = (key: string) => storeColor(key)

  return (
    <ResponsiveContainer width="100%" height={350}>
      <BarChart data={data}>
        <defs>
          {seriesKeys.map((key) => {
            const c = colorFor(key)
            return (
              <linearGradient key={key} id={`bar-${key}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={c} stopOpacity={0.95} />
                <stop offset="100%" stopColor={c} stopOpacity={0.35} />
              </linearGradient>
            )
          })}
        </defs>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={chart.grid} />
        <XAxis
          dataKey="month"
          stroke={chart.axis}
          fontSize={12}
          tickLine={false}
          axisLine={false}
          padding={{ left: 20, right: 20 }}
        />
        <YAxis
          stroke={chart.axis}
          fontSize={12}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value) => `€${value}`}
        />
        <Tooltip
          content={<SpendingTooltip monthLabel={t("analytics.month")} totalLabel={t("common.total")} fmtMoney={fmtMoney} />}
          cursor={{ fill: chart.grid }}
        />
        {seriesKeys.map((key) => (
          <Bar
            key={key}
            dataKey={key}
            stackId="a"
            fill={`url(#bar-${key})`}
            stroke={colorFor(key)}
            strokeOpacity={0.5}
            radius={[3, 3, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
