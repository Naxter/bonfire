"use client"

/**
 * Receipts — import center, searchable receipt history with review states,
 * and the duplicate-resolution panel. Rows link to the detail/review page.
 */

import { Suspense, useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { ChevronLeft, ChevronRight, CopyCheck, Search, X } from "lucide-react"
import { getDuplicateGroups, getReceiptsList, type ReceiptListRow } from "@/lib/api"
import { useDataVersion, useFilters, useApi } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { storeColor } from "@/lib/theme"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { CardState, PanelHeader, ReviewBadge, ScopeLabel } from "@/components/shared/bits"
import { ImportCenter } from "@/components/receipts/ImportCenter"

const LIMIT = 15
const REVIEW_FILTERS = ["all", "needs_review", "verified"] as const

function ReceiptRow({ receipt }: { receipt: ReceiptListRow }) {
  const { t, fmtMoney, fmtDate } = useI18n()
  const key = (receipt.store_key || "").toLowerCase()
  const displayName = key === "rewe" ? "REWE" : key === "dm" ? "DM"
    : key ? key[0].toUpperCase() + key.slice(1) : "Other"
  const accent = storeColor(displayName)
  const initials = ((receipt.store_name || key || "?").replace(/[^A-Za-zÄÖÜäöü]/g, "").slice(0, 2) || "?").toUpperCase()
  return (
    <Link
      href={`/receipts/${receipt.id}`}
      className="group flex items-center rounded-xl border border-border bg-secondary/20 p-3 transition-all duration-200 hover:border-primary/40 hover:bg-secondary/50"
    >
      <Avatar className="h-10 w-10 border" style={{ borderColor: `${accent}55` }}>
        <AvatarFallback className="font-bold" style={{ background: `${accent}1f`, color: accent }}>
          {initials}
        </AvatarFallback>
      </Avatar>
      <div className="ml-4 min-w-0 flex-1 space-y-1">
        <p className="flex items-center gap-2 text-sm font-semibold leading-none">
          <span className="truncate">{receipt.store_name}</span>
          <ReviewBadge status={receipt.review_status} mismatch={receipt.total_mismatch} />
        </p>
        <p className="text-xs text-muted-foreground">
          {fmtDate(receipt.date, "weekday")}
          {receipt.total_mismatch && (
            <span className="ml-2 status-warn">{t("receipts.mismatch")} ({fmtMoney(receipt.items_sum)})</span>
          )}
        </p>
      </div>
      <div className="ml-auto font-mono text-base font-bold neon-cyan">
        -{fmtMoney(receipt.total_amount)}
      </div>
    </Link>
  )
}

function DuplicatesPanel() {
  const { t, fmtMoney, fmtDate } = useI18n()
  const { version } = useDataVersion()
  const { data, error, loading, retry } = useApi(() => getDuplicateGroups(), [version])
  return (
    <div id="duplicates" className="hud-panel overflow-hidden">
      <PanelHeader
        icon={<CopyCheck className="h-4 w-4 text-primary" aria-hidden />}
        title={t("receipts.duplicates.title")}
      />
      <div className="p-4">
        <CardState loading={loading} error={error} retry={retry}
                   empty={(data ?? []).length === 0} emptyText={t("receipts.duplicates.none")} minH="min-h-[60px]">
          <p className="mb-3 text-xs text-muted-foreground">{t("receipts.duplicates.hint")}</p>
          <div className="space-y-3">
            {(data ?? []).map((group) => (
              <div key={`${group.store_key}-${group.date}-${group.total}`} className="rounded-lg border border-[var(--warn)]/30 bg-[var(--warn)]/5 p-3">
                <div className="text-sm font-semibold text-foreground">
                  {group.receipts[0]?.store_name} · {fmtDate(group.date)} · {fmtMoney(group.total)}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-2">
                  {group.receipts.map((r) => (
                    <Link key={r.id} href={`/receipts/${r.id}`}
                          className="rounded-md border border-border bg-secondary/40 px-2 py-1 text-xs font-medium text-foreground hover:border-primary/40">
                      #{r.id} · {fmtDate(r.date, "datetime")}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardState>
      </div>
    </div>
  )
}

function ReceiptsContent() {
  const { t } = useI18n()
  const { store, range } = useFilters()
  const { version } = useDataVersion()
  const params = useSearchParams()

  const [review, setReview] = useState<string>(params.get("review") ?? "all")
  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")
  const [receipts, setReceipts] = useState<ReceiptListRow[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [isFetching, setIsFetching] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const requestSeq = useRef(0)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  const loadPage = useCallback(async (page: number) => {
    const seq = ++requestSeq.current
    setIsFetching(true)
    setLoadError(false)
    try {
      const data = await getReceiptsList(page, LIMIT, {
        store, search: debouncedSearch, start: range.start, end: range.end, review,
      })
      if (seq !== requestSeq.current) return
      setReceipts(data.items || [])
      setTotalCount(data.total || 0)
      setTotalPages(Math.ceil((data.total || 0) / LIMIT) || 1)
    } catch {
      if (seq === requestSeq.current) setLoadError(true)
    } finally {
      if (seq === requestSeq.current) setIsFetching(false)
    }
  }, [store, range.start, range.end, review, debouncedSearch])

  // Any filter change resets to the first page — adjusted during render (the
  // React-sanctioned pattern), not in an effect, so there's no double fetch.
  const filterKey = [store, range.start, range.end, review, debouncedSearch].join(" ")
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey)
  if (prevFilterKey !== filterKey) {
    setPrevFilterKey(filterKey)
    setCurrentPage(1)
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadPage(currentPage)
  }, [currentPage, loadPage, version])

  return (
    <div className="space-y-5 p-4 sm:p-6 lg:p-8">
      <ImportCenter />

      <div className="hud-panel overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
          <h2 className="font-display text-sm font-bold tracking-wide text-foreground">{t("receipts.title").toUpperCase()}</h2>
          <ScopeLabel />
        </div>
        <div className="space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("receipts.searchPlaceholder")}
                aria-label={t("common.search")}
                className="h-9 w-full rounded-md border border-primary/20 bg-secondary/40 pl-9 pr-9 text-sm text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
              />
              {search && (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label={t("common.close")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              )}
            </div>
            <div className="flex items-center gap-1 rounded-lg border border-primary/20 bg-secondary/40 p-1" role="group">
              {REVIEW_FILTERS.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setReview(key)}
                  aria-pressed={review === key}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    review === key ? "bg-primary/15 text-primary" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {t(`review.filter.${key}`)}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between px-0.5">
            <span className="hud-label">{t("receipts.count", { n: totalCount })}</span>
            {debouncedSearch && <span className="hud-label max-w-[60%] truncate text-primary">“{debouncedSearch}”</span>}
          </div>

          <div className="min-h-[440px] space-y-2">
            {loadError ? (
              <CardState loading={false} error retry={() => loadPage(currentPage)} minH="min-h-[400px]" />
            ) : isFetching && receipts.length === 0 ? (
              <div className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">{t("common.loading")}</div>
            ) : receipts.length === 0 ? (
              <div className="flex h-[400px] items-center justify-center text-sm text-muted-foreground">{t("receipts.noMatch")}</div>
            ) : (
              receipts.map((receipt) => <ReceiptRow key={receipt.id} receipt={receipt} />)
            )}
          </div>

          <div className="flex items-center justify-between border-t border-border pt-4">
            <Button
              variant="outline" size="sm"
              className="border-primary/20 bg-secondary/40 hover:bg-secondary/70"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1 || isFetching}
            >
              <ChevronLeft className="mr-1 h-4 w-4" aria-hidden /> {t("common.previous")}
            </Button>
            <span className="text-sm font-medium text-muted-foreground">
              {t("common.pageOf", { page: currentPage, pages: totalPages })}
            </span>
            <Button
              variant="outline" size="sm"
              className="border-primary/20 bg-secondary/40 hover:bg-secondary/70"
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages || isFetching}
            >
              {t("common.next")} <ChevronRight className="ml-1 h-4 w-4" aria-hidden />
            </Button>
          </div>
        </div>
      </div>

      <DuplicatesPanel />
    </div>
  )
}

export default function ReceiptsPage() {
  return (
    <Suspense fallback={null}>
      <ReceiptsContent />
    </Suspense>
  )
}
