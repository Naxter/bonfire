"use client"

import { useEffect, useState } from "react"
import { getRestock, type RestockItem } from "@/lib/api"
import { ShoppingCart } from "lucide-react"

export function RestockCard() {
  const [items, setItems] = useState<RestockItem[] | null>(null)

  useEffect(() => {
    getRestock(3).then(setItems).catch(() => setItems([]))
  }, [])

  return (
    <div className="hud-panel flex h-[360px] flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border p-4">
        <ShoppingCart className="h-4 w-4 text-primary" />
        <div className="font-display text-sm font-bold tracking-wide text-foreground">RESTOCK RADAR</div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {items === null ? (
          <div className="p-6 text-center text-sm text-muted-foreground">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground">Nothing due right now 🎉</div>
        ) : (
          items.slice(0, 25).map((x, i) => (
            <div key={i} className="flex items-center justify-between gap-2 rounded-md px-2 py-2 hover:bg-secondary/40">
              <div className="min-w-0">
                <div className="truncate text-sm text-foreground">{x.name}</div>
                <div className="hud-label">every ~{x.avg_interval_days}d</div>
              </div>
              <span className={`shrink-0 text-xs font-semibold ${x.overdue ? "text-rose-400" : "text-primary"}`}>
                {x.overdue ? `overdue ${-x.due_in_days}d` : `~${Math.max(x.due_in_days, 0)}d`}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
