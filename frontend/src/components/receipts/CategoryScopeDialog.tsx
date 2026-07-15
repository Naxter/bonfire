"use client"

/**
 * Category changes have reach — this dialog makes it explicit:
 * "everywhere" updates all matching items + future imports (locked mapping),
 * "only this line" touches a single receipt row.
 */

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useI18n } from "@/lib/i18n"

export interface PendingCategoryChange {
  itemId: number
  itemName: string
  newCategory: string
  occurrences: number
}

export function CategoryScopeDialog({ pending, onPick, onCancel }: {
  pending: PendingCategoryChange | null
  onPick: (scope: "all" | "item") => void
  onCancel: () => void
}) {
  const { t } = useI18n()
  return (
    <Dialog open={pending !== null} onOpenChange={(open) => { if (!open) onCancel() }}>
      <DialogContent className="sm:max-w-[440px]">
        <DialogHeader>
          <DialogTitle className="text-base">
            {pending ? t("catscope.title", { name: pending.itemName }) : ""}
          </DialogTitle>
          <DialogDescription>{pending?.newCategory}</DialogDescription>
        </DialogHeader>
        {pending && (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => onPick("all")}
              className="w-full rounded-lg border border-primary/30 bg-primary/10 p-3 text-left transition-colors hover:bg-primary/20"
            >
              <div className="text-sm font-semibold text-primary">{t("catscope.all.title")}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                {t("catscope.all.text", { n: pending.occurrences })}
              </div>
            </button>
            <button
              type="button"
              onClick={() => onPick("item")}
              className="w-full rounded-lg border border-border bg-secondary/40 p-3 text-left transition-colors hover:bg-secondary/70"
            >
              <div className="text-sm font-semibold text-foreground">{t("catscope.item.title")}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{t("catscope.item.text")}</div>
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
