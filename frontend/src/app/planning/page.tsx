"use client"

/**
 * Planning — the actionable side of the data: full shopping list management,
 * the restock radar with actions (+ hidden suggestions with undo), a real
 * pantry, and the meal ideas card.
 */

import { useState } from "react"
import { ListChecks, Package, Plus, Trash2 } from "lucide-react"
import {
  addPantryItem, addShoppingItem, clearCheckedShopping, deletePantryItem,
  deleteShoppingItem, getHiddenRestock, getPantry, getShoppingList,
  undoRestockAction, updatePantryItem, updateShoppingItem,
  type PantryItem, type ShoppingItem,
} from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { MealsCard } from "@/components/dashboard/MealsCard"
import { RestockCard } from "@/components/dashboard/RestockCard"
import { CardState, PanelHeader } from "@/components/shared/bits"
import { toast } from "sonner"

function ShoppingListCard() {
  const { t } = useI18n()
  const { version } = useDataVersion()
  const { data, error, loading, retry, setData } = useApi(() => getShoppingList(), [version])
  const [draft, setDraft] = useState("")

  const mutate = async (fn: () => Promise<void>) => {
    try { await fn() } catch { toast.error(t("common.error")) }
  }

  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const name = draft.trim()
    if (!name) return
    setDraft("")
    void mutate(async () => {
      const created = await addShoppingItem(name)
      setData([created, ...(data ?? []).filter((x) => x.id !== created.id)])
    })
  }

  const toggle = (item: ShoppingItem) => void mutate(async () => {
    const updated = await updateShoppingItem(item.id, { checked: !item.checked })
    setData((data ?? []).map((x) => (x.id === item.id ? updated : x)))
  })

  const remove = (item: ShoppingItem) => void mutate(async () => {
    await deleteShoppingItem(item.id)
    setData((data ?? []).filter((x) => x.id !== item.id))
  })

  const clearDone = () => void mutate(async () => {
    await clearCheckedShopping()
    setData((data ?? []).filter((x) => !x.checked))
  })

  const setQty = (item: ShoppingItem, quantity: number) => {
    if (quantity <= 0) return remove(item)
    void mutate(async () => {
      const updated = await updateShoppingItem(item.id, { quantity })
      setData((data ?? []).map((x) => (x.id === item.id ? updated : x)))
    })
  }

  const open = (data ?? []).filter((x) => !x.checked)
  const done = (data ?? []).filter((x) => x.checked)

  return (
    <div className="hud-panel flex h-[520px] flex-col overflow-hidden">
      <PanelHeader
        icon={<ListChecks className="h-4 w-4 text-primary" aria-hidden />}
        title={t("planning.shopping.title")}
        right={done.length > 0 ? (
          <button type="button" onClick={clearDone}
                  className="text-xs font-semibold text-muted-foreground hover:text-foreground">
            {t("planning.shopping.clearChecked")} ({done.length})
          </button>
        ) : undefined}
      />
      <form onSubmit={add} className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Plus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("planning.shopping.add")}
          aria-label={t("planning.shopping.add")}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </form>
      <div className="flex-1 overflow-y-auto p-2">
        <CardState loading={loading} error={error} retry={retry}
                   empty={(data ?? []).length === 0} emptyText={t("planning.shopping.empty")} minH="min-h-[300px]">
          {[...open, ...done].map((item) => (
            <div key={item.id} className="group flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-secondary/40">
              <input
                type="checkbox" checked={item.checked} onChange={() => toggle(item)}
                aria-label={item.name}
                className="h-4 w-4 accent-[var(--primary)]"
              />
              <span className={`flex-1 truncate text-sm ${item.checked ? "text-muted-foreground line-through" : "text-foreground"}`}>
                {item.name}
              </span>
              {item.source === "restock" && (
                <span className="hud-label shrink-0 text-primary/70">{t("planning.shopping.fromRestock")}</span>
              )}
              {!item.checked && (
                <span className="flex shrink-0 items-center gap-1">
                  <button type="button" onClick={() => setQty(item, item.quantity - 1)}
                          aria-label={`− ${item.name}`}
                          className="h-6 w-6 rounded border border-border text-xs text-muted-foreground hover:text-foreground">−</button>
                  <span className="w-6 text-center font-mono text-xs">{item.quantity}</span>
                  <button type="button" onClick={() => setQty(item, item.quantity + 1)}
                          aria-label={`+ ${item.name}`}
                          className="h-6 w-6 rounded border border-border text-xs text-muted-foreground hover:text-foreground">+</button>
                </span>
              )}
              <button type="button" onClick={() => remove(item)}
                      aria-label={`${t("common.delete")}: ${item.name}`}
                      className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100">
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          ))}
        </CardState>
      </div>
    </div>
  )
}

function HiddenSuggestions() {
  const { t } = useI18n()
  const { version, refresh } = useDataVersion()
  const { data, setData } = useApi(() => getHiddenRestock(), [version])

  if (!data || data.length === 0) return null
  const unhide = async (name: string) => {
    try {
      await undoRestockAction(name)
      setData(data.filter((x) => x.name_key !== name))
      refresh()
    } catch {
      toast.error(t("common.error"))
    }
  }
  return (
    <div className="rounded-lg border border-border bg-secondary/20 p-3">
      <div className="hud-label mb-2">{t("planning.restock.hidden", { n: data.length })}</div>
      <div className="flex flex-wrap gap-1.5">
        {data.map((hidden) => (
          <button
            key={hidden.name_key}
            type="button"
            onClick={() => unhide(hidden.name_key)}
            title={t("planning.restock.unhide")}
            className="rounded-md border border-border bg-secondary/40 px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {hidden.name_key} ↩
          </button>
        ))}
      </div>
    </div>
  )
}

function PantryCard() {
  const { t } = useI18n()
  const { version } = useDataVersion()
  const { data, error, loading, retry, setData } = useApi(() => getPantry(), [version])
  const [draft, setDraft] = useState("")

  const add = (e: React.FormEvent) => {
    e.preventDefault()
    const name = draft.trim()
    if (!name) return
    setDraft("")
    addPantryItem(name).then((created) => {
      setData([...(data ?? []).filter((x) => x.id !== created.id), created].sort((a, b) => a.name.localeCompare(b.name)))
    }).catch(() => toast.error(t("common.error")))
  }

  const setQty = (item: PantryItem, quantity: number) => {
    if (quantity < 0) return
    updatePantryItem(item.id, { quantity }).then((updated) => {
      setData((data ?? []).map((x) => (x.id === item.id ? updated : x)))
    }).catch(() => toast.error(t("common.error")))
  }

  const remove = (item: PantryItem) => {
    deletePantryItem(item.id).then(() => {
      setData((data ?? []).filter((x) => x.id !== item.id))
    }).catch(() => toast.error(t("common.error")))
  }

  return (
    <div className="hud-panel flex h-[520px] flex-col overflow-hidden">
      <PanelHeader
        icon={<Package className="h-4 w-4 text-primary" aria-hidden />}
        title={t("planning.pantry.title")}
      />
      <form onSubmit={add} className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Plus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("planning.pantry.add")}
          aria-label={t("planning.pantry.add")}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </form>
      <div className="flex-1 overflow-y-auto p-2">
        <CardState loading={loading} error={error} retry={retry}
                   empty={(data ?? []).length === 0} emptyText={t("planning.pantry.empty")} minH="min-h-[300px]">
          {(data ?? []).map((item) => (
            <div key={item.id} className="group flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-secondary/40">
              <span className="flex-1 truncate text-sm text-foreground">{item.name}</span>
              {item.category && <span className="hud-label hidden shrink-0 sm:inline">{item.category}</span>}
              <span className="flex shrink-0 items-center gap-1">
                <button type="button" onClick={() => setQty(item, Math.max(0, item.quantity - 1))}
                        aria-label={`− ${item.name}`}
                        className="h-6 w-6 rounded border border-border text-xs text-muted-foreground hover:text-foreground">−</button>
                <span className="w-8 text-center font-mono text-xs">{item.quantity}{item.unit ? ` ${item.unit}` : ""}</span>
                <button type="button" onClick={() => setQty(item, item.quantity + 1)}
                        aria-label={`+ ${item.name}`}
                        className="h-6 w-6 rounded border border-border text-xs text-muted-foreground hover:text-foreground">+</button>
              </span>
              <button type="button" onClick={() => remove(item)}
                      aria-label={`${t("common.delete")}: ${item.name}`}
                      className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive focus-visible:opacity-100 group-hover:opacity-100">
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          ))}
        </CardState>
      </div>
    </div>
  )
}

export default function PlanningPage() {
  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      <div className="grid gap-4 lg:grid-cols-2">
        <ShoppingListCard />
        <div className="space-y-4">
          <RestockCard className="!h-[420px]" />
          <HiddenSuggestions />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <PantryCard />
        <MealsCard className="!h-[520px]" />
      </div>
    </div>
  )
}
