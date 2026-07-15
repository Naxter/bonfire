"use client"

/**
 * Analytics — the detailed charts, moved out of the home screen. Every card
 * respects the global store/time filters where the data allows it and says
 * so via its scope label.
 */

import { useMemo, useState } from "react"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"
import { LineChart as LineChartIcon, Package, Search, X, Zap } from "lucide-react"
import {
  getCategoryData, getMonthlyData, getPriceHistory, getPriceVolatility, getTopProducts,
  getWalletShare, type PricePoint,
} from "@/lib/api"
import { useApi, useDataVersion, useFilters } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { storeColor } from "@/lib/theme"
import { useChartTheme } from "@/lib/use-chart-theme"
import { CategoryPie } from "@/components/dashboard/CategoryPie"
import { OverviewChart } from "@/components/dashboard/OverviewChart"
import { CardState, ScopeLabel, StoreBadge } from "@/components/shared/bits"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

interface PriceTooltipProps {
  active?: boolean
  payload?: { value: number; payload: PricePoint }[]
  fmtMoney?: (n: number) => string
}

function PriceTooltip({ active, payload, fmtMoney }: PriceTooltipProps) {
  if (active && payload && payload.length && fmtMoney) {
    return (
      <div className="rounded-lg border border-border bg-popover/95 p-3 shadow-[0_8px_24px_-10px_rgba(0,0,0,0.6)] backdrop-blur">
        <p className="text-sm font-semibold mb-1">{payload[0].payload.exact_date}</p>
        <p className="text-sm neon-text font-bold">{fmtMoney(payload[0].value)}</p>
      </div>
    )
  }
  return null
}

export default function AnalyticsPage() {
  const { t, fmtMoney } = useI18n()
  const { store, range } = useFilters()
  const { version } = useDataVersion()
  const chart = useChartTheme()

  const [category, setCategory] = useState("all")
  const [prodQuery, setProdQuery] = useState("")
  const [volaQuery, setVolaQuery] = useState("")
  const [selectedItem, setSelectedItem] = useState<string | null>(null)

  const monthly = useApi(() => getMonthlyData(store), [store, version])
  const categories = useApi(
    () => getCategoryData({ store, start: range.start, end: range.end }),
    [store, range.start, range.end, version],
  )
  const products = useApi(
    () => getTopProducts({ store, start: range.start, end: range.end, category }),
    [store, range.start, range.end, category, version],
  )
  const volatility = useApi(() => getPriceVolatility(store), [store, version])
  const wallet = useApi(
    () => getWalletShare({ start: range.start, end: range.end }),
    [range.start, range.end, version],
  )
  const activeItem = selectedItem ?? volatility.data?.[0]?.name ?? null
  const history = useApi<PricePoint[]>(
    () => (activeItem ? getPriceHistory(activeItem, store) : Promise.resolve([])),
    [activeItem, store, version],
  )

  const filteredProducts = useMemo(
    () => (products.data ?? []).filter((p) => p.name?.toLowerCase().includes(prodQuery.toLowerCase())),
    [products.data, prodQuery],
  )
  const filteredVolatility = useMemo(
    () => (volatility.data ?? []).filter((v) => v.name?.toLowerCase().includes(volaQuery.toLowerCase())),
    [volatility.data, volaQuery],
  )

  const allTime = (wallet.data ?? []).reduce((s, x) => s + (x.value || 0), 0)
  const toggleCategory = (name: string) => setCategory((prev) => (prev === name ? "all" : name))

  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      {category !== "all" && (
        <button
          type="button"
          onClick={() => setCategory("all")}
          className="flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary transition-colors hover:bg-primary/20"
        >
          {category} <X className="h-3 w-3" aria-hidden />
        </button>
      )}

      {/* ===== CHARTS ROW ===== */}
      <div className="grid gap-4 lg:grid-cols-7">
        <div className="hud-panel col-span-1 lg:col-span-4 p-5">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-display text-sm font-bold tracking-widest text-foreground">{t("analytics.spendingHistory").toUpperCase()}</h2>
            <ScopeLabel respectsRange={false} />
          </div>
          <CardState loading={monthly.loading} error={monthly.error} retry={monthly.retry} minH="min-h-[350px]">
            <OverviewChart data={monthly.data ?? []} />
          </CardState>
        </div>

        <div className="hud-panel col-span-1 lg:col-span-3 p-5">
          <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="font-display text-sm font-bold tracking-widest text-foreground">{t("analytics.topCategories").toUpperCase()}</h2>
            <span className="hud-label"><ScopeLabel /> · {t("analytics.tapSlice")}</span>
          </div>
          <CardState loading={categories.loading} error={categories.error} retry={categories.retry} minH="min-h-[300px]">
            <CategoryPie
              data={categories.data ?? []}
              activeCategory={category === "all" ? null : category}
              onSelect={toggleCategory}
            />
          </CardState>
        </div>
      </div>

      {/* ===== WALLET SHARE ===== */}
      <div className="hud-panel p-5">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Zap className="h-4 w-4 text-primary" aria-hidden />
            <h2 className="hud-label">{t("analytics.walletShare")}</h2>
          </div>
          <ScopeLabel respectsStore={false} />
        </div>
        <CardState loading={wallet.loading} error={wallet.error} retry={wallet.retry}
                   empty={(wallet.data ?? []).length === 0} emptyText={t("analytics.noPeriodData")} minH="min-h-[60px]">
          <div className="flex h-3 w-full overflow-hidden rounded-full border border-border bg-secondary/40"
               role="img" aria-label={t("analytics.walletShare")}>
            {(wallet.data ?? []).map((s, i) => {
              const pct = allTime ? (s.value / allTime) * 100 : 0
              const c = storeColor(s.name, i)
              return (
                <div key={s.name} style={{ width: `${pct}%`, background: c }} title={`${s.name}: ${fmtMoney(s.value)}`} />
              )
            })}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
            {(wallet.data ?? []).map((s, i) => {
              const pct = allTime ? (s.value / allTime) * 100 : 0
              const c = storeColor(s.name, i)
              return (
                <div key={s.name} className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} aria-hidden />
                  <span className="text-xs text-muted-foreground uppercase tracking-wider">{s.name}</span>
                  <span className="text-xs font-bold text-foreground">{pct.toFixed(0)}% · {fmtMoney(s.value)}</span>
                </div>
              )
            })}
          </div>
        </CardState>
      </div>

      {/* ===== INFLATION TRACKER ===== */}
      <div className="hud-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-secondary/20 px-5 py-4">
          <div className="flex items-center gap-2">
            <LineChartIcon className="h-5 w-5 text-primary" aria-hidden />
            <div>
              <h2 className="font-display text-sm font-bold tracking-widest text-foreground">{t("analytics.inflation.title").toUpperCase()}</h2>
              <div className="hud-label">{t("analytics.inflation.subtitle")}</div>
            </div>
          </div>
          <ScopeLabel respectsRange={false} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 h-[680px] md:h-[430px] overflow-hidden">
          {/* Leaderboard */}
          <div className="col-span-1 flex flex-col border-b border-border md:border-b-0 md:border-r bg-background/20 h-[280px] md:h-full overflow-hidden">
            <div className="shrink-0 space-y-2 border-b border-border px-3 py-2.5">
              <div className="hud-label px-1">{t("analytics.inflation.volatile")}</div>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
                <input
                  value={volaQuery}
                  onChange={(e) => setVolaQuery(e.target.value)}
                  placeholder={t("analytics.inflation.filterItems")}
                  aria-label={t("analytics.inflation.filterItems")}
                  className="h-7 w-full rounded-md border border-primary/20 bg-secondary/40 pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
                />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto min-h-0 p-1.5">
              <CardState loading={volatility.loading} error={volatility.error} retry={volatility.retry}
                         empty={filteredVolatility.length === 0} emptyText={t("analytics.inflation.noMatch")} minH="min-h-[180px]">
                {filteredVolatility.map((item, index) => {
                  const active = activeItem === item.name
                  return (
                    <button
                      key={`${item.name}-${index}`}
                      type="button"
                      onClick={() => setSelectedItem(item.name)}
                      aria-pressed={active}
                      className={`flex w-full items-center justify-between gap-2 rounded-lg p-2.5 text-left transition-all ${active ? "bg-primary/10 ring-1 ring-primary/40" : "hover:bg-secondary/50"}`}
                    >
                      <div className="min-w-0 space-y-1">
                        <div className="flex items-center gap-2 truncate text-sm font-medium">
                          <span className="truncate">{item.name}</span>
                          <StoreBadge name={item.store} index={index} />
                        </div>
                        <div className="text-xs text-muted-foreground">{fmtMoney(item.min_price)} → {fmtMoney(item.max_price)}</div>
                      </div>
                      <div className="shrink-0 font-bold status-bad">+{item.change_percent.toFixed(1)}%</div>
                    </button>
                  )
                })}
              </CardState>
            </div>
          </div>

          {/* Line chart */}
          <div className="col-span-1 md:col-span-2 p-4 md:p-6 flex flex-col h-[400px] md:h-full overflow-hidden">
            <h3 className="font-display text-base font-bold mb-4 shrink-0 truncate tracking-wider">
              {activeItem || t("analytics.inflation.selectProduct")}
            </h3>
            <div className="flex-1 min-h-0 min-w-0">
              {(history.data ?? []).length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={history.data ?? []} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                    <defs>
                      <linearGradient id="priceLine" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor={chart.lineFrom} />
                        <stop offset="100%" stopColor={chart.lineTo} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={chart.grid} />
                    <XAxis dataKey="exact_date" stroke={chart.axis} fontSize={10} tickLine={false} axisLine={false} minTickGap={20} />
                    <YAxis stroke={chart.axis} fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `€${val.toFixed(2)}`} domain={['auto', 'auto']} />
                    <Tooltip content={<PriceTooltip fmtMoney={fmtMoney} />} cursor={{ stroke: chart.cursor, strokeWidth: 1, strokeDasharray: '4 4' }} />
                    <Line
                      type="monotone"
                      dataKey="price"
                      stroke="url(#priceLine)"
                      strokeWidth={2.5}
                      dot={{ r: 2.5, fill: chart.line, stroke: "none" }}
                      activeDot={{ r: 6, fill: chart.lineActive, stroke: chart.pieStroke, strokeWidth: 2 }}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
                  {t("analytics.inflation.noHistory")}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ===== MOST BOUGHT ===== */}
      <div className="hud-panel flex flex-col h-[600px] overflow-hidden">
        <div className="flex flex-col gap-2 border-b border-border p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 font-display text-sm font-bold tracking-widest text-foreground">
            <Package className="h-4 w-4 text-primary" aria-hidden /> {t("analytics.mostBought").toUpperCase()}
            <ScopeLabel />
          </div>
          <div className="relative w-full sm:w-[190px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={prodQuery}
              onChange={(e) => setProdQuery(e.target.value)}
              placeholder={t("analytics.filterProducts")}
              aria-label={t("analytics.filterProducts")}
              className="h-8 w-full rounded-md border border-primary/20 bg-secondary/40 pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
            />
          </div>
        </div>
        <div className="flex-1 overflow-hidden">
          <ScrollArea className="h-full w-full">
            <CardState loading={products.loading} error={products.error} retry={products.retry}
                       empty={(products.data ?? []).length === 0} emptyText={t("analytics.noPeriodData")} minH="min-h-[200px]">
              {filteredProducts.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">{t("analytics.noProductsMatch", { q: prodQuery })}</div>
              ) : (
                <Table>
                  <TableHeader className="sticky top-0 bg-background/80 backdrop-blur z-10">
                    <TableRow className="hover:bg-transparent border-border">
                      <TableHead className="hud-label">{t("common.item")}</TableHead>
                      <TableHead className="hud-label text-right">{t("common.quantity")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredProducts.map((item, index) => (
                      <TableRow key={index} className="border-border/60 hover:bg-secondary/40">
                        <TableCell className="font-medium text-sm flex items-center gap-2">
                          {item.name}
                          <StoreBadge name={item.store} index={index} />
                        </TableCell>
                        <TableCell className="text-right font-mono font-semibold neon-cyan">{item.quantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardState>
          </ScrollArea>
        </div>
      </div>
    </div>
  )
}
