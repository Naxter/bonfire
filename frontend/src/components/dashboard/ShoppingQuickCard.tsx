"use client"

import { useState } from "react"
import Link from "next/link"
import { ListChecks, Plus } from "lucide-react"
import { addShoppingItem, getShoppingList, updateShoppingItem, type ShoppingItem } from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { CardState, PanelHeader } from "@/components/shared/bits"
import { toast } from "sonner"

/** Today-page shopping list: check things off, quick-add, jump to planning. */
export function ShoppingQuickCard({ className = "" }: { className?: string }) {
  const { t } = useI18n()
  const { version } = useDataVersion()
  const { data, error, loading, retry, setData } = useApi(() => getShoppingList(), [version])
  const [draft, setDraft] = useState("")

  const toggle = async (item: ShoppingItem) => {
    try {
      const updated = await updateShoppingItem(item.id, { checked: !item.checked })
      setData((data ?? []).map((x) => (x.id === item.id ? updated : x)))
    } catch {
      toast.error(t("common.error"))
    }
  }

  const add = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = draft.trim()
    if (!name) return
    setDraft("")
    try {
      const created = await addShoppingItem(name)
      setData([created, ...(data ?? []).filter((x) => x.id !== created.id)])
    } catch {
      toast.error(t("common.error"))
    }
  }

  const open = (data ?? []).filter((x) => !x.checked)
  const done = (data ?? []).filter((x) => x.checked)

  return (
    <div className={`hud-panel flex h-[420px] flex-col overflow-hidden ${className}`}>
      <PanelHeader
        icon={<ListChecks className="h-4 w-4 text-primary" aria-hidden />}
        title={t("today.shopping.title")}
        right={
          <Link href="/planning" className="text-xs font-semibold text-primary hover:underline">
            {t("today.shopping.open")} →
          </Link>
        }
      />
      <form onSubmit={add} className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Plus className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={t("today.shopping.add")}
          aria-label={t("today.shopping.add")}
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </form>
      <div className="flex-1 overflow-y-auto p-2">
        <CardState
          loading={loading} error={error} retry={retry}
          empty={(data ?? []).length === 0}
          emptyText={t("today.shopping.empty")}
          minH="min-h-[260px]"
        >
          {[...open, ...done].map((item) => (
            <label key={item.id}
                   className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-secondary/40">
              <input
                type="checkbox"
                checked={item.checked}
                onChange={() => toggle(item)}
                className="h-4 w-4 accent-[var(--primary)]"
                aria-label={item.name}
              />
              <span className={`flex-1 truncate text-sm ${item.checked ? "text-muted-foreground line-through" : "text-foreground"}`}>
                {item.name}
                {item.quantity > 1 ? ` ×${item.quantity}` : ""}
              </span>
              {item.source === "restock" && (
                <span className="hud-label shrink-0 text-primary/70">{t("planning.shopping.fromRestock")}</span>
              )}
            </label>
          ))}
        </CardState>
      </div>
    </div>
  )
}
