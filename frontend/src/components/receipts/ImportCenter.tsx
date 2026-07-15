"use client"

/**
 * Unified import center: drag-and-drop PDFs/photos, click-to-browse, mobile
 * camera capture — everything becomes a tracked job with visible status,
 * failures and retries (the import/error history below the dropzone).
 */

import { useRef, useState } from "react"
import { Camera, UploadCloud } from "lucide-react"
import { errorDetail, uploadReceiptFile } from "@/lib/api"
import { useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { ImportsFeed } from "@/components/dashboard/ImportsFeed"
import { PanelHeader } from "@/components/shared/bits"
import { toast } from "sonner"

const ACCEPTED = [".pdf", ".jpg", ".jpeg", ".png", ".webp"]

export function ImportCenter() {
  const { t } = useI18n()
  const { nudge } = useJobs()
  const inputRef = useRef<HTMLInputElement>(null)
  const cameraRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)

  const upload = async (files: File[]) => {
    if (!files.length) return
    setBusy(true)
    let queued = 0
    for (const file of files) {
      const ext = `.${file.name.split(".").pop()?.toLowerCase()}`
      if (!ACCEPTED.includes(ext)) {
        toast.error(t("import.uploadRejected", { name: file.name }))
        continue
      }
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
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    void upload(Array.from(e.dataTransfer.files))
  }

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader
        icon={<UploadCloud className="h-4 w-4 text-primary" aria-hidden />}
        title={t("import.title")}
      />
      <div className="p-4">
        <div
          role="button"
          tabIndex={0}
          aria-label={t("import.drop")}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click() }}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
            dragging ? "border-primary bg-primary/10" : "border-border bg-secondary/20 hover:border-primary/40"
          } ${busy ? "opacity-60" : ""}`}
        >
          <UploadCloud className="h-8 w-8 text-primary" aria-hidden />
          <p className="max-w-md text-sm text-muted-foreground">
            {dragging ? t("import.dropActive") : t("import.drop")}
          </p>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); cameraRef.current?.click() }}
            className="mt-1 flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 sm:hidden"
          >
            <Camera className="h-3.5 w-3.5" aria-hidden /> {t("header.addReceipt")}
          </button>
        </div>
        <input
          ref={inputRef} type="file" multiple accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => { void upload(Array.from(e.target.files ?? [])); e.target.value = "" }}
        />
        <input
          ref={cameraRef} type="file" accept="image/*" capture="environment"
          className="hidden"
          onChange={(e) => { void upload(Array.from(e.target.files ?? [])); e.target.value = "" }}
        />
      </div>
      <div className="border-t border-border">
        <div className="hud-label px-4 pt-3">{t("import.history")}</div>
        <ImportsFeed limit={12} />
      </div>
    </div>
  )
}
