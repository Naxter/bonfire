"use client"

import { useState } from "react"
import { fetchReweMails, errorDetail } from "@/lib/api"
import { useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { Mail } from "lucide-react"
import { toast } from "sonner"

/** On-demand mailbox sweep, as a tracked background job: the jobs poller
 *  announces the result and refreshes data when the eBons are ingested. */
export function FetchMailsButton() {
  const { t } = useI18n()
  const [busy, setBusy] = useState(false)
  const { nudge } = useJobs()

  const onClick = async () => {
    setBusy(true)
    try {
      await fetchReweMails()
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
      title={t("header.fetchMails.title")}
      className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
    >
      <Mail className="h-3.5 w-3.5" aria-hidden />
      <span className="hidden sm:inline">{busy ? "…" : t("header.fetchMails")}</span>
      <span className="sr-only sm:hidden">{t("header.fetchMails")}</span>
    </button>
  )
}
