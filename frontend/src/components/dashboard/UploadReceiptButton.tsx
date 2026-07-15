"use client"

import { useRef, useState } from "react"
import { uploadReceiptFile, errorDetail } from "@/lib/api"
import { useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { Camera } from "lucide-react"
import { toast } from "sonner"

/** Quick multi-file upload (photos + PDFs). Files become tracked import jobs;
 *  the jobs poller toasts results and refreshes the data — no page reload. */
export function UploadReceiptButton() {
  const { t } = useI18n()
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const { nudge } = useJobs()

  const onFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setBusy(true)
    let queued = 0
    for (const file of files) {
      try {
        await uploadReceiptFile(file)
        queued++
      } catch (err) {
        toast.error(errorDetail(err) || t("import.uploadRejected", { name: file.name }))
      }
    }
    if (queued > 0) {
      toast.info(t("import.uploadQueued", { n: queued }))
      nudge()
    }
    setBusy(false)
    if (inputRef.current) inputRef.current.value = ""
  }

  return (
    <>
      <input ref={inputRef} type="file" accept="image/*,.pdf" multiple className="hidden" onChange={onFiles} />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        title={t("header.addReceipt.title")}
        className="flex h-8 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
      >
        <Camera className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden sm:inline">{busy ? "…" : t("header.addReceipt")}</span>
        <span className="sr-only sm:hidden">{t("header.addReceipt")}</span>
      </button>
    </>
  )
}
