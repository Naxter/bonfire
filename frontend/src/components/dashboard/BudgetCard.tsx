"use client"

import { useEffect, useState } from "react"
import { getBudget, type Budget } from "@/lib/api"
import { Wallet } from "lucide-react"

export function BudgetCard() {
  const [b, setB] = useState<Budget | null>(null)

  useEffect(() => {
    getBudget().then(setB).catch(() => setB(null))
  }, [])

  const dayFrac = b ? Math.min(b.days_elapsed / b.days_in_month, 1) : 0

  return (
    <div className="hud-panel flex h-[420px] flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border p-4">
        <Wallet className="h-4 w-4 text-primary" />
        <div className="font-display text-sm font-bold tracking-wide text-foreground">BUDGET FORECAST</div>
      </div>

      {!b ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">Loading…</div>
      ) : b.spent_so_far === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-1 p-6 text-center">
          <span className="text-sm text-muted-foreground">No spend recorded yet this month.</span>
          <span className="hud-label">{b.month}</span>
        </div>
      ) : (
        <div className="flex flex-1 flex-col overflow-hidden p-4">
          <div className="flex items-baseline justify-between">
            <span className="hud-label">Projected month-end</span>
            <span className="hud-label">day {b.days_elapsed}/{b.days_in_month}</span>
          </div>
          <div className="mt-1 font-display text-3xl font-bold neon-text">€{b.projected_total.toFixed(2)}</div>
          <p className="mt-1 text-xs text-muted-foreground">€{b.spent_so_far.toFixed(2)} spent so far</p>

          <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-secondary/50">
            <div className="h-full rounded-full bg-primary/70" style={{ width: `${dayFrac * 100}%` }} />
          </div>

          <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
            {b.anomalies.length > 0 ? (
              <>
                <div className="hud-label mb-2 text-rose-400/90">Running hot</div>
                {b.anomalies.map((c) => (
                  <div key={c.category} className="flex items-center justify-between py-1 text-sm">
                    <span className="truncate text-foreground">{c.category}</span>
                    <span className="shrink-0 text-xs text-rose-400">
                      €{c.projected.toFixed(0)} vs €{c.avg_month.toFixed(0)}
                      {c.delta_pct != null ? ` (+${c.delta_pct.toFixed(0)}%)` : ""}
                    </span>
                  </div>
                ))}
              </>
            ) : (
              <div className="pt-2 text-sm text-muted-foreground">No category running unusually hot. 👍</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
