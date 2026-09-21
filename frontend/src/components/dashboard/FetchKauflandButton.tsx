"use client"

import { useState } from "react"
import { CloudDownload } from "lucide-react"
import { errorDetail, fetchKauflandReceipts } from "@/lib/api"
import { useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { toast } from "sonner"

/** Start a tracked Kaufland API download using the login configured on the host. */
export function FetchKauflandButton() {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const { nudge } = useJobs()

  const onClick = async () => {
    setBusy(true)
    try {
      await fetchKauflandReceipts()
      nudge()
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={onClick}
      disabled={busy}
      title={t("header.fetchKaufland.title")}
      className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
    >
      <CloudDownload className="h-3.5 w-3.5" aria-hidden />
      <span className="hidden sm:inline">{busy ? "…" : t("header.fetchKaufland")}</span>
      <span className="sr-only sm:hidden">{t("header.fetchKaufland")}</span>
    </button>
  )
}
