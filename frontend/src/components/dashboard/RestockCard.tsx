"use client"

import { useState } from "react"
import Link from "next/link"
import { BellOff, Check, Clock, ListPlus, ShoppingCart } from "lucide-react"
import { getRestock, restockAction, type RestockActionKind, type RestockItem } from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { CardState, PanelHeader, ScopeLabel } from "@/components/shared/bits"
import { toast } from "sonner"

/** Restock radar with actions: put on the list, mark bought, snooze, dismiss.
 *  Suggestions are cadence-based across ALL stores (scope label says so). */
export function RestockCard({ className = "" }: { className?: string }) {
  const { t } = useI18n()
  const { version, refresh } = useDataVersion()
  const { data, error, loading, retry, setData } = useApi(() => getRestock(), [version])
  const [busy, setBusy] = useState<string | null>(null)

  const act = async (item: RestockItem, action: RestockActionKind) => {
    setBusy(item.name)
    try {
      await restockAction(item.name, action)
      setData((data ?? []).filter((x) => x.name !== item.name))
      toast.success(t("planning.restock.actionDone"))
      if (action === "add_to_list") refresh()
    } catch {
      toast.error(t("common.error"))
    } finally {
      setBusy(null)
    }
  }

  const actionButton = (item: RestockItem, action: RestockActionKind, label: string, icon: React.ReactNode) => (
    <button
      type="button"
      onClick={() => act(item, action)}
      disabled={busy === item.name}
      title={label}
      aria-label={`${label}: ${item.name}`}
      className="rounded-md border border-border bg-secondary/50 p-1.5 text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-40"
    >
      {icon}
    </button>
  )

  return (
    <div className={`hud-panel flex h-[420px] flex-col overflow-hidden ${className}`}>
      <PanelHeader
        icon={<ShoppingCart className="h-4 w-4 text-primary" aria-hidden />}
        title={t("planning.restock.title")}
        right={<ScopeLabel respectsStore={false} respectsRange={false} />}
      />
      <div className="flex-1 overflow-y-auto p-2">
        <CardState
          loading={loading}
          error={error}
          retry={retry}
          empty={(data ?? []).length === 0}
          emptyText={t("planning.restock.empty")}
          minH="min-h-[280px]"
        >
          {(data ?? []).slice(0, 25).map((x) => (
            <div key={x.name} className="group rounded-md px-2 py-2 hover:bg-secondary/40">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm text-foreground">{x.name}</div>
                  <div className="hud-label">
                    {t("planning.restock.every", { d: x.avg_interval_days })}
                    {x.suggested_qty > 1 ? ` · ${t("planning.restock.qty", { n: x.suggested_qty })}` : ""}
                  </div>
                </div>
                <span className={`shrink-0 text-xs font-semibold ${x.overdue ? "status-bad" : "text-primary"}`}>
                  {x.overdue
                    ? t("planning.restock.overdue", { d: -x.due_in_days })
                    : t("planning.restock.due", { d: Math.max(x.due_in_days, 0) })}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5">
                {actionButton(x, "add_to_list", t("planning.restock.addToList"), <ListPlus className="h-3.5 w-3.5" aria-hidden />)}
                {actionButton(x, "bought", t("planning.restock.bought"), <Check className="h-3.5 w-3.5" aria-hidden />)}
                {actionButton(x, "snooze", t("planning.restock.snooze"), <Clock className="h-3.5 w-3.5" aria-hidden />)}
                {actionButton(x, "dismiss", t("planning.restock.dismiss"), <BellOff className="h-3.5 w-3.5" aria-hidden />)}
              </div>
            </div>
          ))}
        </CardState>
      </div>
      <div className="border-t border-border p-2 text-center">
        <Link href="/planning" className="text-xs font-semibold text-primary hover:underline">
          {t("today.shopping.open")} →
        </Link>
      </div>
    </div>
  )
}
