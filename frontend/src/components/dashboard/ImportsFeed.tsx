"use client"

import Link from "next/link"
import { CheckCircle2, CircleAlert, CopyCheck, Eye, Loader2, RotateCw } from "lucide-react"
import { retryJob, type ImportJob } from "@/lib/api"
import { useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { toast } from "sonner"

function StatusIcon({ status }: { status: ImportJob["status"] }) {
  if (status === "queued" || status === "running")
    return <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden />
  if (status === "done") return <CheckCircle2 className="h-4 w-4 status-good" aria-hidden />
  if (status === "needs_review") return <Eye className="h-4 w-4 status-warn" aria-hidden />
  if (status === "duplicate") return <CopyCheck className="h-4 w-4 text-muted-foreground" aria-hidden />
  return <CircleAlert className="h-4 w-4 status-bad" aria-hidden />
}

/** Live import queue + history — the visible lifecycle of every ingestion. */
export function ImportsFeed({ limit = 8, showEmpty = true }: { limit?: number; showEmpty?: boolean }) {
  const { t, fmtDate } = useI18n()
  const { jobs, nudge } = useJobs()
  const shown = jobs.slice(0, limit)

  const retry = async (job: ImportJob) => {
    try {
      await retryJob(job.id)
      toast.info(t("import.retried"))
      nudge()
    } catch {
      toast.error(t("common.error"))
    }
  }

  if (shown.length === 0) {
    return showEmpty ? (
      <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t("today.imports.none")}</div>
    ) : null
  }

  return (
    <ul className="divide-y divide-border/60">
      {shown.map((job) => {
        const label = job.message
          || job.filename
          || (job.kind === "mail_fetch" ? t("import.kind.mail_fetch") : `#${job.id}`)
        return (
          <li key={job.id} className="flex items-center gap-3 px-4 py-2.5">
            <StatusIcon status={job.status} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-foreground">
                {job.receipt_id ? (
                  <Link href={`/receipts/${job.receipt_id}`} className="hover:underline">{label}</Link>
                ) : label}
              </div>
              <div className="hud-label">
                {t(`import.kind.${job.kind}`)} · {t(`import.status.${job.status}`)} · {fmtDate(job.created_at, "datetime")}
              </div>
              {job.status === "failed" && job.error && (
                <div className="mt-0.5 truncate text-xs status-bad" title={job.error}>{job.error}</div>
              )}
            </div>
            {job.status === "failed" && (
              <button
                type="button"
                onClick={() => retry(job)}
                title={t("import.retry")}
                className="flex shrink-0 items-center gap-1 rounded-md border border-border bg-secondary/40 px-2 py-1 text-xs font-semibold text-muted-foreground hover:text-foreground"
              >
                <RotateCw className="h-3 w-3" aria-hidden /> {t("import.retry")}
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}
