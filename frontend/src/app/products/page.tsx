"use client"

/**
 * Products — the canonical product layer: browse with unit prices, fix
 * names/sizes/brands, merge duplicates (aliases stick for future imports),
 * per-store price comparison, and the price alerts feed.
 */

import { useEffect, useState } from "react"
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"
import { Boxes, ChevronLeft, ChevronRight, Merge, Search, Split, TrendingUp } from "lucide-react"
import {
  errorDetail, getCategories, getPriceAlerts, getProductDetail, getProducts, mergeProducts,
  splitProduct, updateProduct, type ProductDetail, type ProductRow, type UnitPrice,
} from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { useChartTheme } from "@/lib/use-chart-theme"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CardState, PanelHeader, StoreBadge } from "@/components/shared/bits"
import { toast } from "sonner"

const LIMIT = 25

function UnitPriceLabel({ unitPrice }: { unitPrice: UnitPrice | null }) {
  const { t, fmtMoney } = useI18n()
  if (!unitPrice) return <span className="text-muted-foreground/60">—</span>
  const suffix = unitPrice.unit === "kg" ? t("products.perKg") : unitPrice.unit === "l" ? t("products.perL") : t("products.perPiece")
  return <span>{fmtMoney(unitPrice.value)}{suffix}</span>
}

function PriceAlerts() {
  const { t, fmtMoney, fmtDate } = useI18n()
  const { version } = useDataVersion()
  const { data, error, loading, retry } = useApi(() => getPriceAlerts(), [version])
  return (
    <div id="alerts" className="hud-panel overflow-hidden">
      <PanelHeader
        icon={<TrendingUp className="h-4 w-4 text-primary" aria-hidden />}
        title={t("products.alerts.title")}
        right={<span className="hud-label">{t("products.alerts.hint")}</span>}
      />
      <CardState loading={loading} error={error} retry={retry}
                 empty={(data ?? []).length === 0} emptyText={t("products.alerts.none")} minH="min-h-[80px]">
        <ul className="divide-y divide-border/60">
          {(data ?? []).map((alert) => (
            <li key={`${alert.product_id}-${alert.date}`} className="flex items-center gap-3 px-4 py-2.5">
              <span className="shrink-0 rounded bg-[var(--bad)]/10 px-1.5 py-0.5 text-xs font-bold status-bad">
                +{alert.increase_pct}%
              </span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-foreground">{alert.name}</div>
                <div className="hud-label">{alert.store} · {fmtDate(alert.date)}</div>
              </div>
              <div className="shrink-0 text-right text-sm">
                <div className="font-semibold text-foreground">{fmtMoney(alert.latest_price)}</div>
                <div className="text-xs text-muted-foreground">{t("products.alerts.was", { old: fmtMoney(alert.previous_price) })}</div>
              </div>
            </li>
          ))}
        </ul>
      </CardState>
    </div>
  )
}

function ProductDialog({ productId, onClose, onChanged }: {
  productId: number | null
  onClose: () => void
  onChanged: () => void
}) {
  const { t, fmtMoney, fmtDate } = useI18n()
  const chart = useChartTheme()
  const [detail, setDetail] = useState<ProductDetail | null>(null)
  const [draft, setDraft] = useState({ display_name: "", brand: "", size_value: "", size_unit: "", category: "" })
  const [busy, setBusy] = useState(false)
  const categories = useApi(() => getCategories(), [])
  const categoryOptions = [...(categories.data ?? []), "Uncategorized"]

  useEffect(() => {
    // Reset synchronously so a previously opened product never flashes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDetail(null)
    if (productId === null) return
    getProductDetail(productId).then((d) => {
      setDetail(d)
      setDraft({
        display_name: d.product.display_name,
        brand: d.product.brand ?? "",
        size_value: d.product.size_value ? String(d.product.size_value) : "",
        size_unit: d.product.size_unit ?? "",
        category: d.product.category,
      })
    }).catch(() => toast.error(t("common.errorLoad")))
  }, [productId, t])

  const save = async () => {
    if (!detail) return
    setBusy(true)
    try {
      await updateProduct(detail.product.id, {
        display_name: draft.display_name,
        brand: draft.brand,
        size_value: draft.size_value ? Number(draft.size_value) : null,
        size_unit: draft.size_unit || null,
        ...(draft.category ? { category: draft.category } : {}),
      })
      toast.success(t("products.updated"))
      onChanged()
      onClose()
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  const unmerge = async (nameKey: string) => {
    if (!detail) return
    setBusy(true)
    try {
      const productId = detail.product.id
      await splitProduct(productId, nameKey)
      toast.success(t("products.split.done", { name: nameKey }))
      onChanged()
      setDetail(await getProductDetail(productId))
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  const history = (detail?.history ?? []).map((h) => ({ ...h, label: fmtDate(h.date, "short") }))

  return (
    <Dialog open={productId !== null} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-[640px]">
        <DialogHeader>
          <DialogTitle>{detail?.product.display_name ?? t("common.loading")}</DialogTitle>
        </DialogHeader>
        {detail && (
          <div className="space-y-4">
            {/* Edit fields */}
            <div className="grid grid-cols-2 gap-3">
              <label className="col-span-2 block text-sm">
                <span className="hud-label">{t("common.name")}</span>
                <Input className="mt-1" value={draft.display_name} maxLength={200}
                       onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} />
              </label>
              <label className="block text-sm">
                <span className="hud-label">{t("products.brand")}</span>
                <Input className="mt-1" value={draft.brand} maxLength={80}
                       onChange={(e) => setDraft({ ...draft, brand: e.target.value })} />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="block text-sm">
                  <span className="hud-label">{t("products.size")}</span>
                  <Input className="mt-1" type="number" step="any" min="0" value={draft.size_value}
                         onChange={(e) => setDraft({ ...draft, size_value: e.target.value })} />
                </label>
                <label className="block text-sm">
                  <span className="hud-label">&nbsp;</span>
                  <Select value={draft.size_unit || "none"} onValueChange={(v) => setDraft({ ...draft, size_unit: v === "none" ? "" : v })}>
                    <SelectTrigger className="mt-1 h-9 text-sm"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{t("products.noSize")}</SelectItem>
                      <SelectItem value="g">{t("unit.g")}</SelectItem>
                      <SelectItem value="ml">{t("unit.ml")}</SelectItem>
                      <SelectItem value="piece">{t("unit.piece")}</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
              </div>
              <label className="block text-sm">
                <span className="hud-label">{t("common.category")}</span>
                <Select value={draft.category || undefined} onValueChange={(v) => setDraft({ ...draft, category: v })}>
                  <SelectTrigger className="mt-1 h-9 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent className="max-h-[280px]">
                    {categoryOptions.map((c) => (
                      <SelectItem key={c} value={c}>{c}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
            </div>

            {/* Store comparison */}
            <div>
              <div className="hud-label mb-2">{t("products.detail.stores")}</div>
              <div className="space-y-1.5">
                {detail.stores.map((s, i) => (
                  <div key={s.store_key} className="flex items-center gap-2 rounded-md bg-secondary/30 px-3 py-2 text-sm">
                    <StoreBadge name={s.store} />
                    <span className="text-xs text-muted-foreground">{t("products.detail.purchases", { n: s.purchases })}</span>
                    <span className="ml-auto font-mono font-semibold">{fmtMoney(s.latest_price)}</span>
                    {s.unit_price && <span className="text-xs text-muted-foreground"><UnitPriceLabel unitPrice={s.unit_price} /></span>}
                    {i === 0 && detail.stores.length > 1 && (
                      <span className="rounded bg-[var(--good)]/15 px-1.5 py-0.5 text-[10px] font-bold status-good">
                        {t("products.detail.cheapest")}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Price history */}
            {history.length > 1 && (
              <div>
                <div className="hud-label mb-2">{t("products.detail.history")}</div>
                <div className="h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history} margin={{ top: 5, right: 10, left: -14, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={chart.grid} />
                      <XAxis dataKey="label" stroke={chart.axis} fontSize={10} tickLine={false} axisLine={false} minTickGap={24} />
                      <YAxis stroke={chart.axis} fontSize={11} tickLine={false} axisLine={false}
                             tickFormatter={(v) => `€${Number(v).toFixed(2)}`} domain={["auto", "auto"]} />
                      <Tooltip
                        formatter={(value) => [fmtMoney(Number(value)), ""]}
                        labelFormatter={(label) => String(label)}
                        contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
                      />
                      <Line type="monotone" dataKey="price" stroke={chart.line} strokeWidth={2}
                            dot={{ r: 2, fill: chart.line, stroke: "none" }} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Merged names — each one can be split back into its own product */}
            {detail.aliases.length > 0 && (
              <div>
                <div className="hud-label mb-1">{t("products.detail.merged")}</div>
                <div className="flex flex-wrap gap-1.5">
                  {detail.aliases.map((key) => (
                    <span key={key} className="flex items-center gap-1 rounded bg-secondary/50 py-0.5 pl-1.5 pr-1 text-xs text-muted-foreground">
                      {key}
                      <button
                        type="button"
                        onClick={() => unmerge(key)}
                        disabled={busy}
                        title={t("products.split.hint")}
                        aria-label={`${t("products.split")}: ${key}`}
                        className="rounded p-0.5 hover:bg-secondary hover:text-foreground disabled:opacity-50"
                      >
                        <Split className="h-3 w-3" aria-hidden />
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Receipt spellings that resolve here on their own (not mergeable apart) */}
            {(() => {
              const plain = detail.receipt_names.filter(
                (n) => !detail.aliases.includes(n.toLowerCase().trim()),
              )
              return plain.length > 1 ? (
                <div>
                  <div className="hud-label mb-1">{t("products.detail.aliases")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {plain.map((name) => (
                      <span key={name} className="rounded bg-secondary/50 px-1.5 py-0.5 text-xs text-muted-foreground">{name}</span>
                    ))}
                  </div>
                </div>
              ) : null
            })()}
          </div>
        )}
        <DialogFooter>
          <button
            type="button"
            onClick={save}
            disabled={busy || !detail}
            className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
          >
            {busy ? t("common.saving") : t("common.save")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function ProductsPage() {
  const { t, fmtMoney, fmtDate } = useI18n()
  const { version, refresh } = useDataVersion()
  const [search, setSearch] = useState("")
  const [debounced, setDebounced] = useState("")
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<number[]>([])
  const [mergeOpen, setMergeOpen] = useState(false)
  const [mergeTarget, setMergeTarget] = useState<number | null>(null)
  const [openProduct, setOpenProduct] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => { setDebounced(search); setPage(1) }, 300)
    return () => clearTimeout(timer)
  }, [search])

  const products = useApi(
    () => getProducts({ search: debounced, page, limit: LIMIT, sort: "last_purchased" }),
    [debounced, page, version],
  )
  const rows = products.data?.items ?? []
  const totalPages = Math.max(1, Math.ceil((products.data?.total ?? 0) / LIMIT))

  const toggleSelect = (id: number) => {
    setSelected((current) => current.includes(id) ? current.filter((x) => x !== id) : [...current, id])
  }

  const selectedRows = rows.filter((r) => selected.includes(r.id))

  const doMerge = async () => {
    if (mergeTarget === null || selected.length < 2) return
    setBusy(true)
    try {
      const sources = selected.filter((id) => id !== mergeTarget)
      await mergeProducts(mergeTarget, sources)
      toast.success(t("products.merge.done", { n: sources.length }))
      setSelected([])
      setMergeOpen(false)
      setMergeTarget(null)
      refresh()
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      <div className="hud-panel overflow-hidden">
        <PanelHeader
          icon={<Boxes className="h-4 w-4 text-primary" aria-hidden />}
          title={t("products.title")}
          right={<span className="hud-label hidden max-w-md text-right sm:block">{t("products.subtitle")}</span>}
        />
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("products.search")}
                aria-label={t("products.search")}
                className="h-9 w-full rounded-md border border-primary/20 bg-secondary/40 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground outline-none focus:border-primary/40"
              />
            </div>
            <button
              type="button"
              disabled={selected.length < 2}
              onClick={() => { setMergeTarget(selected[0]); setMergeOpen(true) }}
              title={t("products.merge.hint")}
              className="flex h-9 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-40"
            >
              <Merge className="h-3.5 w-3.5" aria-hidden /> {t("products.merge")} ({selected.length})
            </button>
          </div>

          <CardState loading={products.loading} error={products.error} retry={products.retry}
                     empty={rows.length === 0} emptyText={t("products.empty")} minH="min-h-[300px]">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="border-border hover:bg-transparent">
                    <TableHead className="w-[36px]"><span className="sr-only">{t("products.merge")}</span></TableHead>
                    <TableHead className="hud-label">{t("common.name")}</TableHead>
                    <TableHead className="hud-label hidden md:table-cell">{t("common.category")}</TableHead>
                    <TableHead className="hud-label hidden sm:table-cell">{t("products.size")}</TableHead>
                    <TableHead className="hud-label text-right">{t("products.timesBought")}</TableHead>
                    <TableHead className="hud-label text-right">{t("products.lastPrice")}</TableHead>
                    <TableHead className="hud-label hidden text-right sm:table-cell">{t("products.unitPrice")}</TableHead>
                    <TableHead className="hud-label hidden text-right lg:table-cell">{t("products.lastPurchased")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((p: ProductRow) => (
                    <TableRow key={p.id} className="border-border/60 hover:bg-secondary/40">
                      <TableCell>
                        <input
                          type="checkbox"
                          checked={selected.includes(p.id)}
                          onChange={() => toggleSelect(p.id)}
                          aria-label={`${t("products.merge")}: ${p.display_name}`}
                          className="h-4 w-4 accent-[var(--primary)]"
                        />
                      </TableCell>
                      <TableCell>
                        <button type="button" onClick={() => setOpenProduct(p.id)}
                                className="flex max-w-[320px] items-center gap-2 text-left text-sm font-medium hover:text-primary">
                          <span className="truncate">{p.display_name}</span>
                          {p.stores.slice(0, 2).map((s) => <StoreBadge key={s.key} name={s.name} />)}
                        </button>
                        {p.brand && <div className="hud-label">{p.brand}</div>}
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground md:table-cell">{p.category}</TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                        {p.size_value ? `${p.size_value} ${t(`unit.${p.size_unit}`)}` : "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {p.times_bought}
                        {p.total_qty > p.times_bought && (
                          <div className="hud-label">{t("products.totalQty", { n: p.total_qty })}</div>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm">
                        {p.last_price !== null ? fmtMoney(p.last_price) : "—"}
                      </TableCell>
                      <TableCell className="hidden text-right font-mono text-xs text-muted-foreground sm:table-cell">
                        <UnitPriceLabel unitPrice={p.unit_price} />
                      </TableCell>
                      <TableCell className="hidden text-right text-xs text-muted-foreground lg:table-cell">
                        {p.last_purchased ? fmtDate(p.last_purchased) : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="flex items-center justify-between border-t border-border pt-3">
              <Button variant="outline" size="sm" className="border-primary/20 bg-secondary/40"
                      onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                <ChevronLeft className="mr-1 h-4 w-4" aria-hidden /> {t("common.previous")}
              </Button>
              <span className="text-sm text-muted-foreground">{t("common.pageOf", { page, pages: totalPages })}</span>
              <Button variant="outline" size="sm" className="border-primary/20 bg-secondary/40"
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
                {t("common.next")} <ChevronRight className="ml-1 h-4 w-4" aria-hidden />
              </Button>
            </div>
          </CardState>
        </div>
      </div>

      <PriceAlerts />

      {/* Merge dialog: pick which one survives */}
      <Dialog open={mergeOpen} onOpenChange={setMergeOpen}>
        <DialogContent className="sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle>{t("products.merge.title", { n: selected.length })}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("products.merge.hint")}</p>
          <div className="space-y-1.5">
            {selectedRows.map((p) => (
              <label key={p.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border p-3 ${
                mergeTarget === p.id ? "border-primary/50 bg-primary/10" : "border-border bg-secondary/30"
              }`}>
                <input
                  type="radio"
                  name="merge-target"
                  checked={mergeTarget === p.id}
                  onChange={() => setMergeTarget(p.id)}
                  className="h-4 w-4 accent-[var(--primary)]"
                />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{p.display_name}</div>
                  <div className="hud-label">{p.times_bought}× · {p.category}</div>
                </div>
                {mergeTarget === p.id && (
                  <span className="ml-auto shrink-0 text-xs font-semibold text-primary">{t("products.merge.keep")}</span>
                )}
              </label>
            ))}
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={doMerge}
              disabled={busy || mergeTarget === null}
              className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {busy ? t("common.saving") : t("products.merge")}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ProductDialog productId={openProduct} onClose={() => setOpenProduct(null)} onChanged={refresh} />
    </div>
  )
}
