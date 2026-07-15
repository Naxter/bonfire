"use client"

import Link from "next/link"
import { Wallet } from "lucide-react"
import { getBudget } from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { CardState, PanelHeader, ScopeLabel } from "@/components/shared/bits"

/** Compact budget summary: forecast + remaining vs target + hottest alerts.
 *  Full targets editing lives on /budget. Data is all-stores, current month. */
export function BudgetCard({ className = "" }: { className?: string }) {
  const { t, fmtMoney } = useI18n()
  const { version } = useDataVersion()
  const { data: b, error, loading, retry } = useApi(() => getBudget(), [version])

  const dayFrac = b ? Math.min(b.days_elapsed / b.days_in_month, 1) : 0
  const spendFrac = b?.target ? Math.min(b.spent_so_far / b.target, 1) : null

  return (
    <div className={`hud-panel flex h-[420px] flex-col overflow-hidden ${className}`}>
      <PanelHeader
        icon={<Wallet className="h-4 w-4 text-primary" aria-hidden />}
        title={t("nav.budget")}
        right={<ScopeLabel respectsStore={false} override={`${t("filters.allStores")} · ${t("scope.thisMonth")}`} />}
      />
      <CardState loading={loading} error={error} retry={retry} minH="min-h-[300px]">
        {b && (
          <div className="flex flex-1 flex-col overflow-hidden p-4">
            <div className="flex items-baseline justify-between">
              <span className="hud-label">{t("today.kpi.projected")}</span>
              <span className="hud-label">{t("today.kpi.day", { d: b.days_elapsed, n: b.days_in_month })}</span>
            </div>
            <div className="mt-1 font-display text-3xl font-bold neon-text">{fmtMoney(b.projected_total)}</div>
            <p className="mt-1 text-xs text-muted-foreground">{t("budget.forecast.spent", { n: fmtMoney(b.spent_so_far) })}</p>

            {/* Progress: budget consumption when a target exists, else month progress */}
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-secondary/50"
                 role="progressbar"
                 aria-valuenow={Math.round((spendFrac ?? dayFrac) * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div
                className={`h-full rounded-full ${spendFrac !== null && b.over_target ? "bg-[var(--bad)]" : "bg-primary/70"}`}
                style={{ width: `${(spendFrac ?? dayFrac) * 100}%` }}
              />
            </div>
            {b.target !== null ? (
              <p className={`mt-1.5 text-xs font-semibold ${b.over_target ? "status-bad" : b.projected_over_target ? "status-warn" : "status-good"}`}>
                {b.remaining !== null && b.remaining >= 0
                  ? t("budget.left", { n: fmtMoney(b.remaining) })
                  : t("budget.over", { n: fmtMoney(Math.abs(b.remaining ?? 0)) })}
                {b.projected_over_target && !b.over_target ? ` · ${t("budget.projectedOver")}` : ""}
              </p>
            ) : (
              <p className="mt-1.5 text-xs text-muted-foreground">
                <Link href="/budget" className="text-primary hover:underline">{t("today.kpi.setBudget")} →</Link>
              </p>
            )}

            <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
              {(b.alerts?.length ?? 0) > 0 ? (
                <>
                  <div className="hud-label mb-2 status-warn">{t("budget.alerts.title")}</div>
                  {b.alerts.map((c) => (
                    <div key={c.category} className="flex items-center justify-between py-1 text-sm">
                      <span className="truncate text-foreground">{c.category}</span>
                      <span className={`shrink-0 text-xs ${c.over_target ? "status-bad" : "status-warn"}`}>
                        {c.target !== null
                          ? t("budget.spent", { spent: fmtMoney(c.spent), target: fmtMoney(c.target) })
                          : `${fmtMoney(c.projected)} vs ${fmtMoney(c.avg_month)}`}
                      </span>
                    </div>
                  ))}
                </>
              ) : (
                <div className="pt-2 text-sm text-muted-foreground">{t("budget.alerts.none")}</div>
              )}
            </div>
            <div className="border-t border-border pt-2 text-center">
              <Link href="/budget" className="text-xs font-semibold text-primary hover:underline">
                {t("nav.budget")} →
              </Link>
            </div>
          </div>
        )}
      </CardState>
    </div>
  )
}
