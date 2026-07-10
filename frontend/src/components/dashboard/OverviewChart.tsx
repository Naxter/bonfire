"use client"

import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts"
import { storeColor, CHART } from "@/lib/theme"

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    const total = payload.reduce((sum: number, entry: any) => sum + entry.value, 0);
    return (
      <div className="rounded-lg border border-border bg-popover/95 p-3 shadow-[0_8px_24px_-10px_rgba(0,0,0,0.6)] backdrop-blur min-w-[150px]">
        <div className="flex flex-col mb-2 border-b border-border pb-2">
          <span className="hud-label">Month</span>
          <span className="font-bold text-foreground">{label}</span>
        </div>
        <div className="space-y-1.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-[2px]" style={{ backgroundColor: entry.color }} />
                <span className="text-xs text-muted-foreground uppercase font-medium tracking-wider">{entry.name}</span>
              </div>
              <span className="font-bold text-sm">€{entry.value.toFixed(2)}</span>
            </div>
          ))}
          {payload.length > 1 && (
            <div className="flex items-center justify-between gap-4 pt-1.5 mt-1.5 border-t border-border">
              <span className="text-xs font-bold uppercase text-primary tracking-wider">Total</span>
              <span className="font-bold text-sm neon-text">€{total.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
    )
  }
  return null
}

export function OverviewChart({ data }: { data: any[] }) {
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
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART.grid} />
        <XAxis
          dataKey="month"
          stroke={CHART.axis}
          fontSize={12}
          tickLine={false}
          axisLine={false}
          padding={{ left: 20, right: 20 }}
        />
        <YAxis
          stroke={CHART.axis}
          fontSize={12}
          tickLine={false}
          axisLine={false}
          tickFormatter={(value) => `€${value}`}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(150,170,190,0.07)' }} />
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
