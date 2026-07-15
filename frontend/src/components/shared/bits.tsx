"use client"

/** Small shared UI pieces: card states, scope labels, badges. */

import Link from "next/link"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { useFilters } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { storeColor } from "@/lib/theme"

/** Standard loading / error / empty body for data cards. */
export function CardState({ loading, error, retry, empty, emptyText, children, minH = "min-h-[120px]" }: {
  loading: boolean
  error: boolean
  retry: () => void
  empty?: boolean
  emptyText?: string
  minH?: string
  children?: React.ReactNode
}) {
  const { t } = useI18n()
  if (loading) {
    return (
      <div className={`flex ${minH} items-center justify-center`} role="status" aria-live="polite">
        <span className="text-sm text-muted-foreground">{t("common.loading")}</span>
      </div>
    )
  }
  if (error) {
    return (
      <div className={`flex ${minH} flex-col items-center justify-center gap-2 text-center`} role="alert">
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <AlertTriangle className="h-4 w-4 status-warn" aria-hidden /> {t("common.errorLoad")}
        </span>
        <button
          type="button"
          onClick={retry}
          className="flex items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 py-1.5 text-xs font-semibold text-foreground hover:bg-secondary/70"
        >
          <RefreshCw className="h-3 w-3" aria-hidden /> {t("common.retry")}
        </button>
      </div>
    )
  }
  if (empty) {
    return (
      <div className={`flex ${minH} items-center justify-center px-4 text-center`}>
        <span className="text-sm text-muted-foreground">{emptyText}</span>
      </div>
    )
  }
  return <>{children}</>
}

/** "REWE · This month" — every card says what data it's showing. */
export function ScopeLabel({ respectsStore = true, respectsRange = true, override }: {
  respectsStore?: boolean
  respectsRange?: boolean
  override?: string
}) {
  const { t } = useI18n()
  const { store, range } = useFilters()
  if (override) return <span className="hud-label">{override}</span>
  const storePart = respectsStore
    ? (store === "all" ? t("filters.allStores") : store.toUpperCase())
    : t("filters.allStores")
  const rangePart = respectsRange
    ? (range.label.startsWith("range.") ? t(range.label) : range.label)
    : t("range.all")
  return <span className="hud-label whitespace-nowrap">{storePart} · {rangePart}</span>
}

export function StoreBadge({ name, index = 0 }: { name: string; index?: number }) {
  const color = storeColor(name, index)
  return (
    <span
      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider"
      style={{ background: `${color}1f`, color }}
    >
      {name}
    </span>
  )
}

export function ReviewBadge({ status, mismatch }: { status: string; mismatch?: boolean }) {
  const { t } = useI18n()
  if (status === "needs_review") {
    return (
      <span className="shrink-0 rounded border border-[var(--warn)]/50 bg-[var(--warn)]/10 px-1.5 py-0.5 text-[10px] font-bold tracking-wider status-warn">
        {t("review.needs_review")}{mismatch ? " · Σ" : ""}
      </span>
    )
  }
  if (status === "verified") {
    return (
      <span className="shrink-0 rounded border border-[var(--good)]/50 bg-[var(--good)]/10 px-1.5 py-0.5 text-[10px] font-bold tracking-wider status-good">
        {t("review.verified")}
      </span>
    )
  }
  return null
}

/** Panel headline with icon + optional scope on the right. */
export function PanelHeader({ icon, title, right, className = "" }: {
  icon?: React.ReactNode
  title: string
  right?: React.ReactNode
  className?: string
}) {
  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 border-b border-border p-4 ${className}`}>
      <div className="flex items-center gap-2">
        {icon}
        <h2 className="font-display text-sm font-bold tracking-wide text-foreground">{title.toUpperCase()}</h2>
      </div>
      {right}
    </div>
  )
}

/** Attention chip on the Today page. */
export function AttentionChip({ href, tone, children }: {
  href: string
  tone: "warn" | "bad" | "info"
  children: React.ReactNode
}) {
  const toneClass = tone === "bad"
    ? "border-[var(--bad)]/40 bg-[var(--bad)]/10 status-bad"
    : tone === "warn"
      ? "border-[var(--warn)]/40 bg-[var(--warn)]/10 status-warn"
      : "border-primary/30 bg-primary/10 text-primary"
  return (
    <Link href={href} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-opacity hover:opacity-80 ${toneClass}`}>
      {children}
    </Link>
  )
}
