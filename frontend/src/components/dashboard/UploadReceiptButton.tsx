"use client"

import { useRef, useState } from "react"
import axios from "axios"
import { uploadReceiptImage } from "@/lib/api"
import { Camera } from "lucide-react"
import { toast } from "sonner"

export function UploadReceiptButton() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setBusy(true)
    const id = toast.loading("Reading receipt…")
    try {
      const d = await uploadReceiptImage(file)
      if (d.stored) {
        toast.success(`Added ${d.store_name} — ${d.items} items, €${d.total.toFixed(2)}`, { id })
      } else {
        toast.info(`Already had that ${d.store_name} receipt (€${d.total.toFixed(2)}).`, { id })
      }
      // let the dashboard reflect the new receipt
      setTimeout(() => window.location.reload(), 1200)
    } catch (err) {
      const data = axios.isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined) : undefined
      toast.error(data?.detail || "Couldn't read a receipt from that image.", { id })
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ""
    }
  }

  return (
    <>
      <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={onFile} />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        title="Photograph / upload a receipt from any store"
        className="flex h-8 items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-3 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
      >
        <Camera className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{busy ? "…" : "Add receipt"}</span>
      </button>
    </>
  )
}
