"use client"

/**
 * App chrome: collapsible desktop sidebar, top bar with the GLOBAL filters
 * (store + time range) and live status, and a bottom nav on mobile.
 *
 * The overview stays the home screen; the sidebar is information architecture,
 * not a generic admin dashboard.
 */

import { useEffect, useMemo, useState } from "react"
import Image from "next/image"
import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  BarChart3, Boxes, ChevronLeft, ChevronRight, Home, ListChecks, Loader2,
  MoreHorizontal, Receipt, Settings, Wallet, X,
} from "lucide-react"
import { getHealth, getNeedsReviewCount, getStores, type Health } from "@/lib/api"
import { useDataVersion, useFilters, useJobs } from "@/lib/app-state"
import { useI18n } from "@/lib/i18n"
import { registerStores } from "@/lib/theme"
import { FetchMailsButton } from "@/components/dashboard/FetchMailsButton"
import { UploadReceiptButton } from "@/components/dashboard/UploadReceiptButton"
import { TimeRange } from "@/components/dashboard/TimeRange"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

const NAV = [
  { href: "/", key: "nav.today", icon: Home },
  { href: "/receipts", key: "nav.receipts", icon: Receipt, badge: true },
  { href: "/analytics", key: "nav.analytics", icon: BarChart3 },
  { href: "/products", key: "nav.products", icon: Boxes },
  { href: "/planning", key: "nav.planning", icon: ListChecks },
  { href: "/budget", key: "nav.budget", icon: Wallet },
  { href: "/settings", key: "nav.settings", icon: Settings },
] as const

const MOBILE_PRIMARY = ["/", "/receipts", "/analytics", "/planning"]
const SIDEBAR_KEY = "bonfire.sidebar"

function useActive(href: string): boolean {
  const pathname = usePathname()
  if (href === "/") return pathname === "/"
  return pathname === href || pathname.startsWith(`${href}/`)
}

function NavLink({ item, collapsed, badge, onNavigate }: {
  item: (typeof NAV)[number]
  collapsed: boolean
  badge: number
  onNavigate?: () => void
}) {
  const { t } = useI18n()
  const active = useActive(item.href)
  const Icon = item.icon
  const label = t(item.key)
  const showBadge = "badge" in item && item.badge && badge > 0
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      title={collapsed ? label : undefined}
      aria-current={active ? "page" : undefined}
      className={`relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
      } ${collapsed ? "justify-center px-2" : ""}`}
    >
      <Icon className="h-4.5 w-4.5 shrink-0" aria-hidden />
      {!collapsed && <span className="truncate">{label}</span>}
      {showBadge ? (
        <span
          aria-label={t("today.reviewCount", { n: badge })}
          className={`flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground ${
            collapsed ? "absolute -right-0.5 -top-0.5" : "ml-auto"
          }`}
        >
          {badge > 99 ? "99+" : badge}
        </span>
      ) : null}
    </Link>
  )
}

function HealthDot() {
  const { t } = useI18n()
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    const load = () =>
      getHealth()
        .then(setHealth)
        .catch(() => setHealth({
          status: "degraded", db: false, llm_provider: "unreachable",
          llm_configured: false, mail_configured: false, auth_enabled: false,
        }))
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [])

  const ok = health?.status === "ok"
  const down = health ? !health.db : false
  const dot = !health ? "bg-muted-foreground" : ok ? "bg-primary pulse-dot" : down ? "bg-[var(--bad)]" : "bg-[var(--warn)]"
  const label = !health ? "…" : ok ? t("status.live") : down ? t("status.offline") : t("status.degraded")
  const tip = health
    ? `LLM: ${health.llm_provider}${health.llm_configured ? "" : ` (${t("common.notConfigured")})`} · DB ${health.db ? "ok" : "down"}`
    : t("status.checking")
  return (
    <div className="hidden items-center gap-2 md:flex" title={tip}>
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      <span className={`hud-label ${ok ? "text-primary" : down ? "status-bad" : health ? "status-warn" : ""}`}>{label}</span>
    </div>
  )
}

function JobsIndicator() {
  const { t } = useI18n()
  const { active } = useJobs()
  if (active === 0) return null
  return (
    <Link
      href="/receipts"
      className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/10 px-2 py-1 text-xs font-semibold text-primary"
      title={t("status.jobs", { n: active })}
    >
      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      {active}
    </Link>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { t } = useI18n()
  const pathname = usePathname()
  const { store, setStore, range, setRange } = useFilters()
  const { version } = useDataVersion()
  const [collapsed, setCollapsed] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [stores, setStores] = useState<{ key: string; display_name: string }[]>([])
  const [reviewCount, setReviewCount] = useState(0)

  useEffect(() => {
    // localStorage restore is only possible post-mount (hydration boundary).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    try { setCollapsed(window.localStorage.getItem(SIDEBAR_KEY) === "1") } catch { /* ignore */ }
  }, [])
  const toggleSidebar = () => {
    setCollapsed((c) => {
      try { window.localStorage.setItem(SIDEBAR_KEY, c ? "0" : "1") } catch { /* ignore */ }
      return !c
    })
  }

  // Store list once (drives the dropdown + distinct chart colors)…
  useEffect(() => {
    getStores().then((s) => {
      registerStores(s.map((x) => x.display_name))
      setStores(s)
    }).catch(() => setStores([]))
  }, [version])

  // …and the review badge whenever data changes.
  useEffect(() => {
    getNeedsReviewCount().then((r) => setReviewCount(r.count)).catch(() => {})
  }, [version, pathname])

  const title = useMemo(() => {
    const hit = [...NAV].sort((a, b) => b.href.length - a.href.length)
      .find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))
    return hit ? t(hit.key) : "Bonfire"
  }, [pathname, t])

  const moreItems = NAV.filter((n) => !MOBILE_PRIMARY.includes(n.href))

  return (
    <div className="flex min-h-screen">
      {/* ===== Desktop sidebar ===== */}
      <aside
        className={`sticky top-0 z-30 hidden h-screen shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-200 lg:flex ${
          collapsed ? "w-16" : "w-56"
        }`}
      >
        <Link href="/" className={`flex items-center gap-3 px-4 py-4 ${collapsed ? "justify-center px-2" : ""}`}>
          <Image src="/logo.png" alt="Bonfire" width={34} height={34}
                 className="h-8.5 w-8.5 rounded-lg border border-primary/40" />
          {!collapsed && (
            <div className="leading-tight">
              <div className="font-display text-sm font-bold tracking-[0.2em] text-foreground">BONFIRE</div>
              <div className="hud-label">{t("shell.tagline")}</div>
            </div>
          )}
        </Link>
        <nav className="flex-1 space-y-1 px-2 py-2" aria-label="Main">
          {NAV.map((item) => (
            <NavLink key={item.href} item={item} collapsed={collapsed} badge={reviewCount} />
          ))}
        </nav>
        <button
          type="button"
          onClick={toggleSidebar}
          aria-label={collapsed ? t("shell.expand") : t("shell.collapse")}
          className="m-2 flex items-center justify-center gap-2 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" aria-hidden /> : (
            <>
              <ChevronLeft className="h-4 w-4" aria-hidden /> {t("shell.collapse")}
            </>
          )}
        </button>
      </aside>

      {/* ===== Main column ===== */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar: title, status, quick actions, GLOBAL filters */}
        <header className="sticky top-0 z-20 border-b border-border bg-background/70 backdrop-blur-xl">
          <div className="flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 sm:px-6">
            <div className="flex items-center gap-3 lg:hidden">
              <Image src="/logo.png" alt="" width={30} height={30} className="h-7.5 w-7.5 rounded-lg border border-primary/40" />
            </div>
            <h1 className="font-display text-lg font-bold tracking-widest text-foreground">{title.toUpperCase()}</h1>
            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <HealthDot />
              <JobsIndicator />
              <FetchMailsButton />
              <UploadReceiptButton />
            </div>
          </div>
          {/* Global filters — visible on every page so scope is never a mystery */}
          <div className="flex flex-wrap items-center gap-2 border-t border-border/60 px-4 py-2 sm:px-6">
            <div className="flex items-center gap-2">
              <span className="hud-label hidden sm:inline">{t("header.store")}</span>
              <Select value={store} onValueChange={setStore}>
                <SelectTrigger className="h-8 w-[140px] bg-secondary/60 border-primary/20 text-xs" aria-label={t("header.store")}>
                  <SelectValue placeholder={t("filters.allStores")} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("filters.allStores")}</SelectItem>
                  {stores.map((s) => (
                    <SelectItem key={s.key} value={s.key}>{s.display_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <TimeRange value={range} onChange={setRange} />
          </div>
        </header>

        <main className="flex-1 pb-20 lg:pb-0">{children}</main>
      </div>

      {/* ===== Mobile bottom nav ===== */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-sidebar/95 backdrop-blur-xl lg:hidden"
      >
        {NAV.filter((n) => MOBILE_PRIMARY.includes(n.href)).map((item) => {
          const Icon = item.icon
          return (
            <MobileTab key={item.href} href={item.href} label={t(item.key)} badge={"badge" in item && item.badge ? reviewCount : 0}>
              <Icon className="h-5 w-5" aria-hidden />
            </MobileTab>
          )
        })}
        <button
          type="button"
          onClick={() => setMoreOpen(true)}
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium text-muted-foreground"
        >
          <MoreHorizontal className="h-5 w-5" aria-hidden />
          {t("nav.more")}
        </button>
      </nav>

      {/* Mobile "More" sheet */}
      {moreOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label={t("common.close")}
            className="absolute inset-0 bg-black/50"
            onClick={() => setMoreOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 rounded-t-2xl border border-border bg-card p-4 pb-8">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-display text-sm font-bold tracking-widest">{t("nav.more").toUpperCase()}</span>
              <button type="button" onClick={() => setMoreOpen(false)} aria-label={t("common.close")}
                      className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary/60">
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            <div className="space-y-1">
              {moreItems.map((item) => (
                <NavLink key={item.href} item={item} collapsed={false} badge={reviewCount}
                         onNavigate={() => setMoreOpen(false)} />
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function MobileTab({ href, label, badge, children }: {
  href: string; label: string; badge: number; children: React.ReactNode
}) {
  const active = useActive(href)
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium ${
        active ? "text-primary" : "text-muted-foreground"
      }`}
    >
      {children}
      {label}
      {badge > 0 && (
        <span className="absolute right-[22%] top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[9px] font-bold text-primary-foreground">
          {badge > 99 ? "99+" : badge}
        </span>
      )}
    </Link>
  )
}
