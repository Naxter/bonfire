"use client"

/**
 * Today — "what needs my attention?" Attention chips, compact KPIs, the
 * assistant cards (restock/budget/meals), shopping list and the import feed.
 * Detailed charts live under /analytics.
 */

import Link from "next/link"
import { Activity, AlertTriangle, CopyCheck, Euro, Eye, Inbox, TrendingUp } from "lucide-react"
import {
  getBudget, getDashboardStats, getDuplicateGroups, getHealth, getPriceAlerts, getWalletShare,
} from "@/lib/api"
import { useApi, useDataVersion, useFilters } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { AskBar } from "@/components/dashboard/AskBar"
import { BudgetCard } from "@/components/dashboard/BudgetCard"
import { ImportsFeed } from "@/components/dashboard/ImportsFeed"
import { MealsCard } from "@/components/dashboard/MealsCard"
import { RestockCard } from "@/components/dashboard/RestockCard"
import { ShoppingQuickCard } from "@/components/dashboard/ShoppingQuickCard"
import { AttentionChip, CardState, PanelHeader, ScopeLabel } from "@/components/shared/bits"
import { UploadReceiptButton } from "@/components/dashboard/UploadReceiptButton"

function FirstRun() {
  const { t } = useI18n()
  const { data: health } = useApi(() => getHealth(), [])
  return (
    <div className="hud-panel mx-auto max-w-2xl p-8">
      <h2 className="font-display text-2xl font-bold tracking-widest text-foreground">{t("empty.title").toUpperCase()}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("empty.subtitle")}</p>
      <ol className="mt-6 space-y-5">
        <li>
          <div className="text-sm font-semibold text-foreground">{t("empty.step1.title")}</div>
          <p className={`mt-1 text-sm ${health?.mail_configured ? "status-good" : "text-muted-foreground"}`}>
            {health?.mail_configured ? t("empty.step1.ok") : t("empty.step1.missing")}
          </p>
        </li>
        <li>
          <div className="text-sm font-semibold text-foreground">{t("empty.step2.title")}</div>
          <p className="mt-1 text-sm text-muted-foreground">{t("empty.step2.text")}</p>
          <div className="mt-2"><UploadReceiptButton /></div>
        </li>
        <li>
          <div className="text-sm font-semibold text-foreground">{t("empty.step3.title")}</div>
          <p className={`mt-1 text-sm ${health?.llm_configured ? "status-good" : "status-warn"}`}>
            {health?.llm_configured
              ? t("empty.step3.ok", { provider: health.llm_provider })
              : t("empty.step3.missing")}
          </p>
        </li>
      </ol>
    </div>
  )
}

function AttentionStrip() {
  const { t } = useI18n()
  const { version } = useDataVersion()
  const { data: health } = useApi(() => getHealth(), [version])
  const { data: dupes } = useApi(() => getDuplicateGroups(), [version])
  const { data: alerts } = useApi(() => getPriceAlerts(), [version])

  const review = health?.receipts?.needs_review ?? 0
  const failed = health?.imports?.failed_24h ?? 0
  const dupeCount = dupes?.length ?? 0
  const alertCount = alerts?.length ?? 0
  const anything = review + failed + dupeCount + alertCount > 0

  return (
    <div>
      <div className="hud-label mb-2">{t("today.needsAttention")}</div>
      <div className="flex flex-wrap gap-2">
        {review > 0 && (
          <AttentionChip href="/receipts?review=needs_review" tone="warn">
            <Eye className="h-3.5 w-3.5" aria-hidden /> {t("today.reviewCount", { n: review })}
          </AttentionChip>
        )}
        {failed > 0 && (
          <AttentionChip href="/receipts" tone="bad">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {t("today.failedImports", { n: failed })}
          </AttentionChip>
        )}
        {dupeCount > 0 && (
          <AttentionChip href="/receipts#duplicates" tone="warn">
            <CopyCheck className="h-3.5 w-3.5" aria-hidden /> {t("today.duplicates", { n: dupeCount })}
          </AttentionChip>
        )}
        {alertCount > 0 && (
          <AttentionChip href="/products#alerts" tone="info">
            <TrendingUp className="h-3.5 w-3.5" aria-hidden /> {t("today.priceAlerts", { n: alertCount })}
          </AttentionChip>
        )}
        {!anything && (
          <span className="flex items-center gap-2 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground">
            {t("today.allClear")}
          </span>
        )}
      </div>
    </div>
  )
}

export default function TodayPage() {
  const { t, fmtMoney } = useI18n()
  const { store } = useFilters()
  const { version } = useDataVersion()

  const stats = useApi(() => getDashboardStats(store), [store, version])
  const wallet = useApi(() => getWalletShare(), [version])
  const budget = useApi(() => getBudget(), [version])

  const allTime = (wallet.data ?? []).reduce((sum, x) => sum + (x.value || 0), 0)
  const up = (stats.data?.diff_percent ?? 0) >= 0
  const isEmpty = stats.data !== null && stats.data.receipt_count === 0

  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      {isEmpty ? (
        <FirstRun />
      ) : (
        <>
          <AttentionStrip />
          <AskBar />

          {/* ===== KPI STRIP ===== */}
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="hud-panel p-5">
              <div className="flex items-center justify-between">
                <span className="hud-label">{t("today.kpi.month")}</span>
                <Euro className="h-4 w-4 text-primary" aria-hidden />
              </div>
              <CardState loading={stats.loading} error={stats.error} retry={stats.retry} minH="min-h-[64px]">
                {stats.data && (
                  <>
                    <div className="mt-3 font-display text-3xl font-bold neon-text">{fmtMoney(stats.data.current_month_total)}</div>
                    <p className="mt-2 flex items-center gap-1 text-xs">
                      <TrendingUp className={`h-3.5 w-3.5 ${up ? "status-good" : "status-bad rotate-180"}`} aria-hidden />
                      <span className={`font-semibold ${up ? "status-good" : "status-bad"}`}>
                        {up ? "+" : ""}{stats.data.diff_percent}%
                      </span>
                      <span className="text-muted-foreground">{t("today.kpi.vsPrev")}</span>
                    </p>
                  </>
                )}
              </CardState>
              <div className="mt-2"><ScopeLabel respectsRange={false} override={`${store === "all" ? t("filters.allStores") : store.toUpperCase()} · ${t("scope.thisMonth")}`} /></div>
            </div>

            <div className="hud-panel p-5">
              <div className="flex items-center justify-between">
                <span className="hud-label">{t("today.kpi.budgetLeft")}</span>
                <Activity className="h-4 w-4 text-primary" aria-hidden />
              </div>
              <CardState loading={budget.loading} error={budget.error} retry={budget.retry} minH="min-h-[64px]">
                {budget.data && (budget.data.target !== null ? (
                  <>
                    <div className={`mt-3 font-display text-3xl font-bold ${budget.data.over_target ? "status-bad" : "neon-text"}`}>
                      {fmtMoney(budget.data.remaining ?? 0)}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {t("budget.spent", { spent: fmtMoney(budget.data.spent_so_far), target: fmtMoney(budget.data.target) })}
                    </p>
                  </>
                ) : (
                  <>
                    <div className="mt-3 font-display text-xl font-bold text-muted-foreground">{t("today.kpi.noBudget")}</div>
                    <p className="mt-2 text-xs">
                      <Link href="/budget" className="text-primary hover:underline">{t("today.kpi.setBudget")} →</Link>
                    </p>
                  </>
                ))}
              </CardState>
              <div className="mt-2"><ScopeLabel respectsStore={false} respectsRange={false} override={`${t("filters.allStores")} · ${t("scope.thisMonth")}`} /></div>
            </div>

            <div className="hud-panel p-5">
              <div className="flex items-center justify-between">
                <span className="hud-label">{t("today.kpi.allTime")}</span>
                <Activity className="h-4 w-4 text-primary" aria-hidden />
              </div>
              <CardState loading={wallet.loading} error={wallet.error} retry={wallet.retry} minH="min-h-[64px]">
                <div className="mt-3 font-display text-3xl font-bold neon-text">{fmtMoney(allTime)}</div>
                <p className="mt-2 text-xs text-muted-foreground">{t("today.kpi.stores", { n: (wallet.data ?? []).length })}</p>
              </CardState>
              <div className="mt-2"><ScopeLabel respectsStore={false} respectsRange={false} override={`${t("filters.allStores")} · ${t("scope.allTime")}`} /></div>
            </div>
          </div>

          {/* ===== ASSISTANT ROW ===== */}
          <div className="grid gap-4 lg:grid-cols-4">
            <RestockCard />
            <BudgetCard />
            <MealsCard className="lg:col-span-2" />
          </div>

          {/* ===== SHOPPING + IMPORTS ===== */}
          <div className="grid gap-4 lg:grid-cols-2">
            <ShoppingQuickCard />
            <div className="hud-panel flex h-[420px] flex-col overflow-hidden">
              <PanelHeader
                icon={<Inbox className="h-4 w-4 text-primary" aria-hidden />}
                title={t("today.imports.title")}
                right={
                  <Link href="/receipts" className="text-xs font-semibold text-primary hover:underline">
                    {t("today.imports.viewAll")} →
                  </Link>
                }
              />
              <div className="flex-1 overflow-y-auto">
                <ImportsFeed limit={8} />
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
