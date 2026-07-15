"use client"

/**
 * Budget — actual budgeting: monthly + per-category targets, remaining
 * amounts, overspend alerts, and a "what changed vs. last month" explanation
 * of the forecast.
 */

import { useEffect, useState } from "react"
import { AlertTriangle, Wallet } from "lucide-react"
import {
  errorDetail, getBudget, getBudgetTargets, getCategories, putBudgetTargets,
} from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { categoryColor } from "@/lib/theme"
import { Input } from "@/components/ui/input"
import { CardState, PanelHeader, ScopeLabel } from "@/components/shared/bits"
import { toast } from "sonner"

function TargetsEditor({ onSaved }: { onSaved: () => void }) {
  const { t } = useI18n()
  const categories = useApi(() => getCategories(), [])
  const targets = useApi(() => getBudgetTargets(), [])
  const [overall, setOverall] = useState("")
  const [byCategory, setByCategory] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)

  // Server state → editable form drafts, once per (re)load of the targets.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!targets.data) return
    setOverall(targets.data.overall !== null ? String(targets.data.overall) : "")
    setByCategory(Object.fromEntries(
      Object.entries(targets.data.categories).map(([cat, amount]) => [cat, String(amount)]),
    ))
  }, [targets.data])
  /* eslint-enable react-hooks/set-state-in-effect */

  const save = async () => {
    setBusy(true)
    try {
      const cats: Record<string, number | null> = {}
      for (const cat of categories.data ?? []) {
        const raw = (byCategory[cat] ?? "").trim()
        cats[cat] = raw ? Number(raw) : null
      }
      await putBudgetTargets({ overall: overall.trim() ? Number(overall) : null, categories: cats })
      toast.success(t("budget.saved"))
      onSaved()
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader
        icon={<Wallet className="h-4 w-4 text-primary" aria-hidden />}
        title={t("budget.perCategory")}
      />
      <CardState loading={targets.loading || categories.loading} error={targets.error || categories.error}
                 retry={() => { targets.retry(); categories.retry() }} minH="min-h-[200px]">
        <div className="space-y-4 p-4">
          <label className="flex items-center justify-between gap-3">
            <span className="text-sm font-semibold text-foreground">{t("budget.overall")}</span>
            <div className="flex items-center gap-1.5">
              <Input
                type="number" min="0" step="10"
                value={overall}
                onChange={(e) => setOverall(e.target.value)}
                placeholder={t("budget.overall.placeholder")}
                className="h-8 w-28 text-right text-sm"
              />
              <span className="text-sm text-muted-foreground">€</span>
            </div>
          </label>
          <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
            {(categories.data ?? []).map((cat, i) => (
              <label key={cat} className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-2 text-sm text-foreground">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: categoryColor(cat, i) }} aria-hidden />
                  <span className="truncate">{cat}</span>
                </span>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Input
                    type="number" min="0" step="5"
                    value={byCategory[cat] ?? ""}
                    onChange={(e) => setByCategory({ ...byCategory, [cat]: e.target.value })}
                    placeholder="—"
                    aria-label={`${t("budget.perCategory")}: ${cat}`}
                    className="h-8 w-24 text-right text-sm"
                  />
                  <span className="text-sm text-muted-foreground">€</span>
                </div>
              </label>
            ))}
          </div>
          <div className="flex justify-end border-t border-border pt-3">
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {busy ? t("common.saving") : t("common.save")}
            </button>
          </div>
        </div>
      </CardState>
    </div>
  )
}

export default function BudgetPage() {
  const { t, fmtMoney } = useI18n()
  const { version, refresh } = useDataVersion()
  const budget = useApi(() => getBudget(), [version])
  const b = budget.data

  const spendFrac = b?.target ? Math.min(b.spent_so_far / b.target, 1) : null
  const dayFrac = b ? Math.min(b.days_elapsed / b.days_in_month, 1) : 0

  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      {/* ===== Forecast + status ===== */}
      <div className="hud-panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-sm font-bold tracking-widest text-foreground">{t("budget.forecast.title").toUpperCase()}</h2>
          <ScopeLabel respectsStore={false} respectsRange={false} override={`${t("filters.allStores")} · ${t("scope.thisMonth")}`} />
        </div>
        <CardState loading={budget.loading} error={budget.error} retry={budget.retry} minH="min-h-[140px]">
          {b && (
            <div className="mt-3 grid gap-6 md:grid-cols-3">
              <div>
                <div className="hud-label">{t("today.kpi.projected")}</div>
                <div className={`mt-1 font-display text-3xl font-bold ${b.projected_over_target ? "status-warn" : "neon-text"}`}>
                  {fmtMoney(b.projected_total)}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("budget.forecast.spent", { n: fmtMoney(b.spent_so_far) })} · {t("today.kpi.day", { d: b.days_elapsed, n: b.days_in_month })}
                </p>
              </div>
              <div>
                <div className="hud-label">{t("today.kpi.budgetLeft")}</div>
                {b.target !== null ? (
                  <>
                    <div className={`mt-1 font-display text-3xl font-bold ${b.over_target ? "status-bad" : "neon-text"}`}>
                      {fmtMoney(b.remaining ?? 0)}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t("budget.spent", { spent: fmtMoney(b.spent_so_far), target: fmtMoney(b.target) })}
                    </p>
                  </>
                ) : (
                  <div className="mt-1 text-xl font-bold text-muted-foreground">{t("today.kpi.noBudget")}</div>
                )}
              </div>
              <div className="flex flex-col justify-center">
                <div className="h-2 w-full overflow-hidden rounded-full bg-secondary/50"
                     role="progressbar" aria-valuemin={0} aria-valuemax={100}
                     aria-valuenow={Math.round((spendFrac ?? dayFrac) * 100)}>
                  <div
                    className={`h-full rounded-full ${spendFrac !== null && b.over_target ? "bg-[var(--bad)]" : "bg-primary/70"}`}
                    style={{ width: `${(spendFrac ?? dayFrac) * 100}%` }}
                  />
                </div>
                {b.projected_over_target && (
                  <p className="mt-2 flex items-center gap-1.5 text-xs font-semibold status-warn">
                    <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {t("budget.projectedOver")}
                  </p>
                )}
              </div>
            </div>
          )}
        </CardState>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* ===== Alerts ===== */}
        <div className="hud-panel overflow-hidden">
          <PanelHeader
            icon={<AlertTriangle className="h-4 w-4 status-warn" aria-hidden />}
            title={t("budget.alerts.title")}
          />
          <CardState loading={budget.loading} error={budget.error} retry={budget.retry}
                     empty={(b?.alerts ?? []).length === 0} emptyText={t("budget.alerts.none")} minH="min-h-[120px]">
            <ul className="divide-y divide-border/60">
              {(b?.alerts ?? []).map((c) => (
                <li key={c.category} className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm">
                  <span className="truncate text-foreground">{c.category}</span>
                  <span className={`shrink-0 text-xs font-semibold ${c.over_target ? "status-bad" : "status-warn"}`}>
                    {c.target !== null
                      ? (c.over_target
                        ? t("budget.over", { n: fmtMoney(Math.abs(c.remaining ?? 0)) })
                        : t("budget.projectedOver"))
                      : `${fmtMoney(c.projected)} vs Ø ${fmtMoney(c.avg_month)}`}
                  </span>
                </li>
              ))}
            </ul>
          </CardState>
        </div>

        {/* ===== What changed ===== */}
        <div className="hud-panel overflow-hidden">
          <PanelHeader
            icon={<Wallet className="h-4 w-4 text-primary" aria-hidden />}
            title={t("budget.changes.title")}
            right={b ? <span className="hud-label">{t("budget.changes.hint", { d: b.days_elapsed })}</span> : undefined}
          />
          <CardState loading={budget.loading} error={budget.error} retry={budget.retry}
                     empty={(b?.changes ?? []).length === 0} emptyText={t("budget.changes.none")} minH="min-h-[120px]">
            <ul className="divide-y divide-border/60">
              {(b?.changes ?? []).map((change) => (
                <li key={change.category} className="flex items-center justify-between gap-2 px-4 py-2.5 text-sm">
                  <span className="truncate text-foreground">{change.category}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {fmtMoney(change.previous)} → {fmtMoney(change.spent)}
                    <span className={`ml-2 font-bold ${change.delta > 0 ? "status-bad" : "status-good"}`}>
                      {change.delta > 0 ? "+" : ""}{fmtMoney(change.delta)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </CardState>
        </div>
      </div>

      {/* ===== Category table with targets ===== */}
      <div className="hud-panel overflow-hidden">
        <PanelHeader
          icon={<Wallet className="h-4 w-4 text-primary" aria-hidden />}
          title={t("budget.categories.title")}
        />
        <CardState loading={budget.loading} error={budget.error} retry={budget.retry}
                   empty={(b?.categories ?? []).length === 0} emptyText={t("analytics.noPeriodData")} minH="min-h-[120px]">
          <ul className="divide-y divide-border/60">
            {(b?.categories ?? []).map((c, i) => {
              const frac = c.target ? Math.min(c.spent / c.target, 1) : null
              return (
                <li key={c.category} className="px-4 py-2.5">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: categoryColor(c.category, i) }} aria-hidden />
                      <span className="truncate text-foreground">{c.category}</span>
                    </span>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {c.target !== null
                        ? t("budget.spent", { spent: fmtMoney(c.spent), target: fmtMoney(c.target) })
                        : `${fmtMoney(c.spent)} · ${t("budget.noTarget")}`}
                    </span>
                  </div>
                  {frac !== null && (
                    <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-secondary/50">
                      <div className={`h-full rounded-full ${c.over_target ? "bg-[var(--bad)]" : "bg-primary/70"}`}
                           style={{ width: `${frac * 100}%` }} />
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </CardState>
      </div>

      <TargetsEditor onSaved={refresh} />
    </div>
  )
}
