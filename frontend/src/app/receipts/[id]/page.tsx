"use client"

/**
 * Receipt detail — the import-review workflow:
 * archived source next to parsed fields, totals check, inline corrections
 * (header + line items with category scope), verify / reprocess / delete.
 */

import { use, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
  AlertTriangle, ArrowLeft, Check, Eye, EyeOff, FileText, Pencil, Plus,
  RefreshCw, Trash2, UtensilsCrossed,
} from "lucide-react"
import {
  addReceiptItem, deleteReceipt, deleteReceiptItem, errorDetail, getCategories,
  getReceiptDetails, pantryFromReceipt, receiptSourceUrl, reprocessReceipt,
  updateReceipt, updateReceiptItem, verifyReceipt, type ReceiptItem,
} from "@/lib/api"
import { useApi, useDataVersion, useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { CardState, ReviewBadge } from "@/components/shared/bits"
import { CategoryScopeDialog, type PendingCategoryChange } from "@/components/receipts/CategoryScopeDialog"
import { toast } from "sonner"

function ActionButton({ onClick, disabled, tone = "default", title, children }: {
  onClick: () => void
  disabled?: boolean
  tone?: "default" | "primary" | "danger"
  title?: string
  children: React.ReactNode
}) {
  const toneClass = tone === "primary"
    ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/20"
    : tone === "danger"
      ? "border-destructive/40 text-destructive hover:bg-destructive/10"
      : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground"
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`flex h-8 items-center gap-1.5 rounded-md border px-3 text-xs font-semibold transition-colors disabled:opacity-50 ${toneClass}`}
    >
      {children}
    </button>
  )
}

export default function ReceiptDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const receiptId = Number(id)
  const router = useRouter()
  const { t, fmtMoney, fmtDate } = useI18n()
  const { refresh } = useDataVersion()
  const { nudge } = useJobs()

  const [reloadKey, setReloadKey] = useState(0)
  const detail = useApi(() => getReceiptDetails(receiptId), [receiptId, reloadKey])
  const categories = useApi(() => getCategories(), [])
  const reload = () => setReloadKey((k) => k + 1)

  const [showSource, setShowSource] = useState(false)
  const [busy, setBusy] = useState(false)

  // Header edit dialog
  const [editOpen, setEditOpen] = useState(false)
  const [draft, setDraft] = useState({ store_name: "", store_key: "", date: "", total: "" })

  // Item edit / add dialogs
  const [itemEdit, setItemEdit] = useState<ReceiptItem | null>(null)
  const [itemDraft, setItemDraft] = useState({ name: "", quantity: "", price_total: "" })
  const [addOpen, setAddOpen] = useState(false)
  const [addDraft, setAddDraft] = useState({ name: "", quantity: "1", price_total: "", category: "Uncategorized" })

  // Category scope
  const [pendingCategory, setPendingCategory] = useState<PendingCategoryChange | null>(null)

  const data = detail.data
  const receipt = data?.receipt

  const run = async (fn: () => Promise<unknown>, successMsg?: string, andRefresh = true) => {
    setBusy(true)
    try {
      await fn()
      if (successMsg) toast.success(successMsg)
      reload()
      if (andRefresh) refresh()
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  const openEdit = () => {
    if (!receipt) return
    const d = new Date(receipt.date)
    const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    setDraft({
      store_name: receipt.store_name,
      store_key: receipt.store_key,
      date: local,
      total: String(receipt.total_amount),
    })
    setEditOpen(true)
  }

  const saveHeader = () => run(async () => {
    await updateReceipt(receiptId, {
      store_name: draft.store_name,
      store_key: draft.store_key,
      date: draft.date,
      total_amount: Number(draft.total),
    })
    setEditOpen(false)
  }, t("detail.edited.toast"))

  const openItemEdit = (item: ReceiptItem) => {
    setItemEdit(item)
    setItemDraft({ name: item.name, quantity: String(item.quantity), price_total: String(item.price_total) })
  }

  const saveItem = () => {
    if (!itemEdit) return
    void run(async () => {
      await updateReceiptItem(receiptId, itemEdit.id, {
        name: itemDraft.name,
        quantity: Number(itemDraft.quantity),
        price_total: Number(itemDraft.price_total),
      })
      setItemEdit(null)
    }, t("detail.item.updated"))
  }

  const addItem = () => void run(async () => {
    await addReceiptItem(receiptId, {
      name: addDraft.name,
      quantity: Number(addDraft.quantity) || 1,
      price_total: Number(addDraft.price_total),
      category: addDraft.category,
    })
    setAddOpen(false)
    setAddDraft({ name: "", quantity: "1", price_total: "", category: "Uncategorized" })
  }, t("detail.item.added"))

  const removeItem = (item: ReceiptItem) => {
    if (!window.confirm(t("detail.deleteItem.confirm", { name: item.name }))) return
    void run(() => deleteReceiptItem(receiptId, item.id), t("detail.item.deleted"))
  }

  const onCategoryPicked = (item: ReceiptItem, newCategory: string) => {
    if (newCategory === item.category) return
    const occurrences = (data?.items ?? []).filter((x) => x.name === item.name).length
    setPendingCategory({ itemId: item.id, itemName: item.name, newCategory, occurrences })
  }

  const applyCategory = (scope: "all" | "item") => {
    const pending = pendingCategory
    setPendingCategory(null)
    if (!pending) return
    void run(async () => {
      const result = await updateReceiptItem(receiptId, pending.itemId, {
        category: pending.newCategory, category_scope: scope,
      })
      toast.success(t("catscope.updated", { name: pending.itemName, category: pending.newCategory }), {
        description: result.updated_items > 1 ? t("catscope.updatedMany", { n: result.updated_items }) : undefined,
      })
    })
  }

  const doVerify = () => void run(() => verifyReceipt(receiptId), t("detail.verified.toast"))
  const doReprocess = () => void run(async () => {
    await reprocessReceipt(receiptId)
    toast.info(t("detail.reprocess.started"))
    nudge()
  }, undefined)
  const doDelete = async () => {
    if (!data) return
    if (!window.confirm(t("detail.delete.confirm", { n: data.items.length }))) return
    setBusy(true)
    try {
      await deleteReceipt(receiptId)
      toast.success(t("detail.delete.done"))
      refresh()
      router.push("/receipts")
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
      setBusy(false)
    }
  }
  const toPantry = () => void run(async () => {
    const result = await pantryFromReceipt(receiptId)
    toast.success(t("detail.pantry.added", { added: result.added, updated: result.updated }))
  }, undefined, false)

  const categoryOptions = [...(categories.data ?? []), "Uncategorized"]

  return (
    <div className="space-y-4 p-4 sm:p-6 lg:p-8">
      <Link href="/receipts" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" aria-hidden /> {t("detail.back")}
      </Link>

      <CardState loading={detail.loading} error={detail.error} retry={detail.retry} minH="min-h-[400px]">
        {data && receipt && (
          <>
            {/* ===== Header ===== */}
            <div className="hud-panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="font-display text-xl font-bold tracking-wide text-foreground">{receipt.store_name}</h1>
                    <ReviewBadge status={receipt.review_status} mismatch={data.total_mismatch} />
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {fmtDate(receipt.date, "datetime")} · {t(`detail.extraction.${receipt.extraction_source}`) }
                  </p>
                </div>
                <div className="text-right">
                  <div className="font-display text-3xl font-bold neon-text">{fmtMoney(receipt.total_amount)}</div>
                  <div className={`mt-0.5 text-xs ${data.total_mismatch ? "status-warn font-semibold" : "text-muted-foreground"}`}>
                    {t("detail.itemsSum")}: {fmtMoney(data.items_sum)}
                  </div>
                </div>
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <ActionButton onClick={openEdit} disabled={busy}>
                  <Pencil className="h-3.5 w-3.5" aria-hidden /> {t("common.edit")}
                </ActionButton>
                {receipt.review_status !== "verified" && (
                  <ActionButton onClick={doVerify} disabled={busy} tone="primary">
                    <Check className="h-3.5 w-3.5" aria-hidden /> {t("detail.verify")}
                  </ActionButton>
                )}
                {receipt.has_source && (
                  <>
                    <ActionButton onClick={() => setShowSource((s) => !s)} disabled={busy} title={t("detail.source.hint")}>
                      {showSource ? <EyeOff className="h-3.5 w-3.5" aria-hidden /> : <Eye className="h-3.5 w-3.5" aria-hidden />}
                      {showSource ? t("detail.source.hide") : t("detail.source.show")}
                    </ActionButton>
                    <ActionButton onClick={doReprocess} disabled={busy} title={t("detail.reprocess.hint")}>
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t("detail.reprocess")}
                    </ActionButton>
                  </>
                )}
                <ActionButton onClick={toPantry} disabled={busy}>
                  <UtensilsCrossed className="h-3.5 w-3.5" aria-hidden /> {t("detail.pantry.add")}
                </ActionButton>
                <div className="ml-auto">
                  <ActionButton onClick={doDelete} disabled={busy} tone="danger">
                    <Trash2 className="h-3.5 w-3.5" aria-hidden /> {t("detail.delete")}
                  </ActionButton>
                </div>
              </div>

              {/* Warnings */}
              {(receipt.parse_warnings.length > 0 || data.total_mismatch) && (
                <div className="mt-4 rounded-lg border border-[var(--warn)]/40 bg-[var(--warn)]/10 p-3" role="alert">
                  <div className="flex items-center gap-2 text-sm font-semibold status-warn">
                    <AlertTriangle className="h-4 w-4" aria-hidden /> {t("detail.warnings.title")}
                  </div>
                  <ul className="mt-1.5 list-disc space-y-0.5 pl-6 text-sm text-foreground/90">
                    {receipt.parse_warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              {/* Duplicates */}
              {data.duplicates.length > 0 && (
                <div className="mt-3 rounded-lg border border-[var(--warn)]/40 bg-[var(--warn)]/5 p-3 text-sm">
                  <span className="font-semibold status-warn">{t("detail.duplicates.warning", { n: data.duplicates.length })} </span>
                  {data.duplicates.map((d) => (
                    <Link key={d.id} href={`/receipts/${d.id}`} className="mr-2 text-primary hover:underline">#{d.id}</Link>
                  ))}
                </div>
              )}
            </div>

            {/* ===== Source + items side by side ===== */}
            <div className={`grid gap-4 ${showSource ? "xl:grid-cols-2" : ""}`}>
              {showSource && receipt.has_source && (
                <div className="hud-panel overflow-hidden">
                  <div className="flex items-center gap-2 border-b border-border p-3">
                    <FileText className="h-4 w-4 text-primary" aria-hidden />
                    <span className="hud-label">{t("detail.source.hint")}</span>
                  </div>
                  {receipt.source_kind === "pdf" ? (
                    <iframe
                      src={receiptSourceUrl(receiptId)}
                      title={t("detail.source.hint")}
                      className="h-[70vh] w-full bg-white"
                    />
                  ) : (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={receiptSourceUrl(receiptId)}
                      alt={t("detail.source.hint")}
                      className="max-h-[70vh] w-full object-contain"
                    />
                  )}
                </div>
              )}

              <div className="hud-panel overflow-hidden">
                <div className="flex items-center justify-between border-b border-border p-3">
                  <span className="hud-label">{t("common.items")} · {data.items.length}</span>
                  <ActionButton onClick={() => setAddOpen(true)} disabled={busy}>
                    <Plus className="h-3.5 w-3.5" aria-hidden /> {t("detail.addItem")}
                  </ActionButton>
                </div>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow className="border-border hover:bg-transparent">
                        <TableHead className="hud-label w-[52px]">{t("common.quantity")}</TableHead>
                        <TableHead className="hud-label">{t("common.item")}</TableHead>
                        <TableHead className="hud-label w-[190px]">{t("common.category")}</TableHead>
                        <TableHead className="hud-label text-right">{t("common.price")}</TableHead>
                        <TableHead className="w-[84px]"><span className="sr-only">{t("common.actions")}</span></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.items.map((item) => (
                        <TableRow key={item.id} className="border-border/60 hover:bg-secondary/40">
                          <TableCell className="font-medium text-muted-foreground">{item.quantity}</TableCell>
                          <TableCell className="font-medium">
                            <span className={item.is_discounted ? "status-good" : ""} title={item.name}>{item.name}</span>
                          </TableCell>
                          <TableCell>
                            <Select
                              value={item.category || "Uncategorized"}
                              onValueChange={(v) => onCategoryPicked(item, v)}
                            >
                              <SelectTrigger
                                aria-label={`${t("common.category")}: ${item.name}`}
                                className="h-8 border-transparent bg-transparent text-xs font-medium text-primary shadow-none hover:border-primary/30 hover:bg-secondary/60 focus:ring-0 focus:ring-offset-0"
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {categoryOptions.map((cat) => (
                                  <SelectItem key={cat} value={cat} className="text-xs">{cat}</SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                          </TableCell>
                          <TableCell className={`text-right font-mono font-medium ${item.price_total < 0 ? "status-good" : ""}`}>
                            {fmtMoney(item.price_total)}
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center justify-end gap-1">
                              <button type="button" onClick={() => openItemEdit(item)}
                                      aria-label={`${t("common.edit")}: ${item.name}`}
                                      className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary/60 hover:text-foreground">
                                <Pencil className="h-3.5 w-3.5" aria-hidden />
                              </button>
                              <button type="button" onClick={() => removeItem(item)}
                                      aria-label={`${t("common.delete")}: ${item.name}`}
                                      className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive">
                                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                              </button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <div className="flex items-center justify-between border-t border-border p-4">
                  <span className={`text-sm ${data.total_mismatch ? "status-warn font-semibold" : "text-muted-foreground"}`}>
                    {data.total_mismatch
                      ? `${t("detail.itemsSum")}: ${fmtMoney(data.items_sum)} ≠ ${fmtMoney(receipt.total_amount)}`
                      : t("detail.totalsOk")}
                  </span>
                  <span className="font-display text-2xl font-bold neon-text">{fmtMoney(receipt.total_amount)}</span>
                </div>
              </div>
            </div>
          </>
        )}
      </CardState>

      {/* ===== Edit header dialog ===== */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader><DialogTitle>{t("detail.editHeader")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="hud-label">{t("common.store")}</span>
              <Input className="mt-1" value={draft.store_name}
                     onChange={(e) => setDraft({ ...draft, store_name: e.target.value })} maxLength={120} />
            </label>
            <label className="block text-sm">
              <span className="hud-label">store key</span>
              <Input className="mt-1 font-mono" value={draft.store_key}
                     onChange={(e) => setDraft({ ...draft, store_key: e.target.value })} maxLength={40} />
            </label>
            <label className="block text-sm">
              <span className="hud-label">{t("common.date")}</span>
              <Input className="mt-1" type="datetime-local" value={draft.date}
                     onChange={(e) => setDraft({ ...draft, date: e.target.value })} />
            </label>
            <label className="block text-sm">
              <span className="hud-label">{t("common.total")} (€)</span>
              <Input className="mt-1" type="number" step="0.01" min="0" value={draft.total}
                     onChange={(e) => setDraft({ ...draft, total: e.target.value })} />
            </label>
          </div>
          <DialogFooter>
            <ActionButton onClick={saveHeader} disabled={busy} tone="primary">
              {busy ? t("common.saving") : t("common.save")}
            </ActionButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ===== Edit item dialog ===== */}
      <Dialog open={itemEdit !== null} onOpenChange={(open) => { if (!open) setItemEdit(null) }}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader><DialogTitle>{t("common.edit")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="hud-label">{t("common.name")}</span>
              <Input className="mt-1" value={itemDraft.name}
                     onChange={(e) => setItemDraft({ ...itemDraft, name: e.target.value })} maxLength={200} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm">
                <span className="hud-label">{t("common.quantity")}</span>
                <Input className="mt-1" type="number" step="0.001" min="0" value={itemDraft.quantity}
                       onChange={(e) => setItemDraft({ ...itemDraft, quantity: e.target.value })} />
              </label>
              <label className="block text-sm">
                <span className="hud-label">{t("common.price")} (€)</span>
                <Input className="mt-1" type="number" step="0.01" value={itemDraft.price_total}
                       onChange={(e) => setItemDraft({ ...itemDraft, price_total: e.target.value })} />
              </label>
            </div>
          </div>
          <DialogFooter>
            <ActionButton onClick={saveItem} disabled={busy} tone="primary">
              {busy ? t("common.saving") : t("common.save")}
            </ActionButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ===== Add item dialog ===== */}
      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader><DialogTitle>{t("detail.addItem")}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <label className="block text-sm">
              <span className="hud-label">{t("common.name")}</span>
              <Input className="mt-1" value={addDraft.name}
                     onChange={(e) => setAddDraft({ ...addDraft, name: e.target.value })} maxLength={200} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-sm">
                <span className="hud-label">{t("common.quantity")}</span>
                <Input className="mt-1" type="number" step="0.001" min="0" value={addDraft.quantity}
                       onChange={(e) => setAddDraft({ ...addDraft, quantity: e.target.value })} />
              </label>
              <label className="block text-sm">
                <span className="hud-label">{t("common.price")} (€)</span>
                <Input className="mt-1" type="number" step="0.01" value={addDraft.price_total}
                       onChange={(e) => setAddDraft({ ...addDraft, price_total: e.target.value })} />
              </label>
            </div>
            <label className="block text-sm">
              <span className="hud-label">{t("common.category")}</span>
              <Select value={addDraft.category} onValueChange={(v) => setAddDraft({ ...addDraft, category: v })}>
                <SelectTrigger className="mt-1 h-9 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {categoryOptions.map((cat) => (
                    <SelectItem key={cat} value={cat} className="text-xs">{cat}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          </div>
          <DialogFooter>
            <ActionButton onClick={addItem} disabled={busy || !addDraft.name.trim() || !addDraft.price_total} tone="primary">
              {busy ? t("common.saving") : t("common.add")}
            </ActionButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CategoryScopeDialog
        pending={pendingCategory}
        onPick={applyCategory}
        onCancel={() => setPendingCategory(null)}
      />
    </div>
  )
}
