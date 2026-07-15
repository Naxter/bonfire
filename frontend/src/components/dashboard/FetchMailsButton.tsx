"use client"

import { useState } from "react"
import axios from "axios"
import { fetchReweMails } from "@/lib/api"
import { Mail } from "lucide-react"
import { toast } from "sonner"

export function FetchMailsButton() {
  const [busy, setBusy] = useState(false)

  const onClick = async () => {
    setBusy(true)
    const id = toast.loading("Checking the mailbox…")
    try {
      const d = await fetchReweMails()
      if (d.saved > 0) {
        toast.success(
          `${d.saved} new eBon${d.saved > 1 ? "s" : ""} fetched — ingesting now…`,
          { id },
        )
        // give the watcher a moment to parse before showing the result
        setTimeout(() => window.location.reload(), 8000)
      } else {
        toast.info("Mailbox checked — nothing new.", { id })
      }
    } catch (err) {
      const data = axios.isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined) : undefined
      toast.error(data?.detail || "Mail fetch failed.", { id })
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      onClick={onClick}
      disabled={busy}
      title="Fetch REWE eBons from your mailbox now (the scraper also polls hourly)"
      className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
    >
      <Mail className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">{busy ? "…" : "Fetch mails"}</span>
    </button>
  )
}
