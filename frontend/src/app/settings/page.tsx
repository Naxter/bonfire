"use client"

/**
 * Settings — appearance & language, insight knobs (DB-backed), integrations
 * health, the optional API token for this browser, and data export.
 * Credentials/schedules stay in .env by design.
 */

import { useEffect, useState } from "react"
import { useTheme } from "next-themes"
import {
  Database, Download, Globe, HeartPulse, Settings as SettingsIcon, ShieldCheck, Sparkles,
} from "lucide-react"
import {
  errorDetail, exportUrls, getApiToken, getHealth, getMealProfiles, getSettings,
  recategorize, setApiToken, updateSettings, type AppSettings, type Health,
} from "@/lib/api"
import { useApi, useDataVersion } from "@/lib/app-state"
import { useI18n, type Locale } from "@/lib/i18n"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { CardState, PanelHeader } from "@/components/shared/bits"
import { toast } from "sonner"

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 py-2.5">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function NumberSetting({ value, onChange, min, max, step = 1 }: {
  value: number; onChange: (n: number) => void; min: number; max: number; step?: number
}) {
  return (
    <Input
      type="number" min={min} max={max} step={step} value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-8 w-24 text-right text-sm"
    />
  )
}

function AppearanceSection() {
  const { t, locale, setLocale } = useI18n()
  const { theme, setTheme } = useTheme()
  const [mounted, setMounted] = useState(false)
  // Hydration boundary: the active theme is only known on the client.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), [])

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader icon={<Globe className="h-4 w-4 text-primary" aria-hidden />} title={t("settings.appearance.title")} />
      <div className="divide-y divide-border/60 px-4 py-1">
        <Row label={t("settings.language")}>
          <Select value={locale} onValueChange={(v) => setLocale(v as Locale)}>
            <SelectTrigger className="h-8 w-40 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="en">{t("settings.language.en")}</SelectItem>
              <SelectItem value="de">{t("settings.language.de")}</SelectItem>
            </SelectContent>
          </Select>
        </Row>
        <Row label={t("settings.theme")}>
          {mounted && (
            <Select value={theme ?? "dark"} onValueChange={setTheme}>
              <SelectTrigger className="h-8 w-40 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="dark">{t("settings.theme.dark")}</SelectItem>
                <SelectItem value="light">{t("settings.theme.light")}</SelectItem>
                <SelectItem value="system">{t("settings.theme.system")}</SelectItem>
                <SelectItem value="hc">{t("settings.theme.hc")}</SelectItem>
              </SelectContent>
            </Select>
          )}
        </Row>
      </div>
    </div>
  )
}

function InsightsSection() {
  const { t } = useI18n()
  const settings = useApi(() => getSettings(), [])
  const profiles = useApi(() => getMealProfiles(), [])
  const [draft, setDraft] = useState<AppSettings | null>(null)
  const [busy, setBusy] = useState(false)

  // Server state → editable form draft, once per (re)load of the settings.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { if (settings.data) setDraft(settings.data) }, [settings.data])

  const save = async () => {
    if (!draft) return
    setBusy(true)
    try {
      await updateSettings(draft)
      toast.success(t("settings.saved"))
    } catch (err) {
      toast.error(t("settings.saveFailed", { msg: errorDetail(err) ?? "" }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader
        icon={<SettingsIcon className="h-4 w-4 text-primary" aria-hidden />}
        title={t("settings.insights.title")}
        right={<span className="hud-label hidden sm:block">{t("settings.insights.desc")}</span>}
      />
      <CardState loading={settings.loading || !draft} error={settings.error} retry={settings.retry} minH="min-h-[200px]">
        {draft && (
          <div className="divide-y divide-border/60 px-4 py-1">
            <Row label={t("settings.meals.profile")}>
              <Select value={draft["meals.profile"]} onValueChange={(v) => setDraft({ ...draft, "meals.profile": v })}>
                <SelectTrigger className="h-8 w-44 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(profiles.data ?? []).map((p) => (
                    <SelectItem key={p.key} value={p.key} className="text-xs">{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Row>
            <Row label={t("settings.meals.count")}>
              <NumberSetting value={draft["meals.count"]} min={1} max={6}
                             onChange={(n) => setDraft({ ...draft, "meals.count": n })} />
            </Row>
            <Row label={t("settings.meals.context")}>
              <Select value={draft["meals.context"]}
                      onValueChange={(v) => setDraft({ ...draft, "meals.context": v as "trip" | "days" })}>
                <SelectTrigger className="h-8 w-44 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="trip">{t("settings.meals.context.trip")}</SelectItem>
                  <SelectItem value="days">{t("settings.meals.context.days")}</SelectItem>
                </SelectContent>
              </Select>
            </Row>
            <Row label={t("settings.meals.days")}>
              <NumberSetting value={draft["meals.days"]} min={3} max={60}
                             onChange={(n) => setDraft({ ...draft, "meals.days": n })} />
            </Row>
            <Row label={t("settings.restock.horizon")}>
              <NumberSetting value={draft["restock.horizon_days"]} min={1} max={14}
                             onChange={(n) => setDraft({ ...draft, "restock.horizon_days": n })} />
            </Row>
            <Row label={t("settings.restock.minPurchases")}>
              <NumberSetting value={draft["restock.min_purchases"]} min={2} max={10}
                             onChange={(n) => setDraft({ ...draft, "restock.min_purchases": n })} />
            </Row>
            <Row label={t("settings.budget.history")}>
              <NumberSetting value={draft["budget.history_months"]} min={2} max={24}
                             onChange={(n) => setDraft({ ...draft, "budget.history_months": n })} />
            </Row>
            <Row label={t("settings.budget.anomaly")}>
              <NumberSetting value={draft["budget.anomaly_factor"]} min={1.1} max={5} step={0.1}
                             onChange={(n) => setDraft({ ...draft, "budget.anomaly_factor": n })} />
            </Row>
            <Row label={t("settings.alerts.pct")}>
              <NumberSetting value={draft["alerts.price_increase_pct"]} min={5} max={100} step={5}
                             onChange={(n) => setDraft({ ...draft, "alerts.price_increase_pct": n })} />
            </Row>
            <div className="flex justify-end py-3">
              <button
                type="button" onClick={save} disabled={busy}
                className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
              >
                {busy ? t("common.saving") : t("common.save")}
              </button>
            </div>
          </div>
        )}
      </CardState>
    </div>
  )
}

function IntegrationsSection() {
  const { t, fmtDate } = useI18n()
  const { version } = useDataVersion()
  const health = useApi(() => getHealth(), [version])
  const [probing, setProbing] = useState(false)
  const [probe, setProbe] = useState<Health["llm_probe"] | null>(null)

  const runProbe = async () => {
    setProbing(true)
    try {
      const result = await getHealth(true)
      setProbe(result.llm_probe ?? null)
      if (result.llm_probe?.reachable) {
        toast.success(t("settings.integrations.llmProbeOk", { ms: result.llm_probe.latency_ms ?? 0 }))
      } else {
        toast.error(t("settings.integrations.llmProbeFail", { msg: result.llm_probe?.error ?? "?" }))
      }
    } catch {
      toast.error(t("common.error"))
    } finally {
      setProbing(false)
    }
  }

  const h = health.data
  const when = (iso: string | null | undefined) => (iso ? fmtDate(iso, "datetime") : t("common.never"))

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader icon={<HeartPulse className="h-4 w-4 text-primary" aria-hidden />} title={t("settings.integrations.title")} />
      <CardState loading={health.loading} error={health.error} retry={health.retry} minH="min-h-[200px]">
        {h && (
          <div className="divide-y divide-border/60 px-4 py-1">
            <Row label={t("settings.integrations.llm")}
                 hint={`${h.llm_provider}${h.llm_configured ? "" : ` · ${t("common.notConfigured")}`}`}>
              <div className="flex items-center gap-2">
                {probe && (
                  <span className={`text-xs font-semibold ${probe.reachable ? "status-good" : "status-bad"}`}>
                    {probe.reachable ? `${probe.latency_ms} ms` : t("common.unavailable")}
                  </span>
                )}
                <button
                  type="button" onClick={runProbe} disabled={probing}
                  className="flex items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 py-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  <Sparkles className="h-3 w-3" aria-hidden /> {probing ? "…" : t("settings.integrations.llmProbe")}
                </button>
              </div>
            </Row>
            <Row label={t("settings.integrations.mail")}
                 hint={h.mail_configured
                   ? t("settings.integrations.mail.last", { when: when(h.mail?.last_fetch_at) })
                   : t("common.notConfigured")}>
              <span className={`text-xs font-semibold ${h.mail_configured ? (h.mail?.last_fetch_ok === false ? "status-bad" : "status-good") : "text-muted-foreground"}`}>
                {h.mail_configured ? (h.mail?.last_fetch_ok === false ? "✗" : "✓") : "—"}
              </span>
            </Row>
            <Row label={t("settings.integrations.watcher")}
                 hint={h.watcher?.last_seen ? when(h.watcher.last_seen) : t("common.never")}>
              <span className={`text-xs font-semibold ${h.watcher?.alive ? "status-good" : "status-warn"}`}>
                {h.watcher?.alive ? t("settings.integrations.watcher.alive") : t("settings.integrations.watcher.dead")}
              </span>
            </Row>
            <Row label={t("settings.integrations.imports")}
                 hint={t("settings.integrations.failed24h", { n: h.imports?.failed_24h ?? 0 })}>
              <span className="text-xs text-muted-foreground">{when(h.imports?.last_success_at)}</span>
            </Row>
            <Row label={t("settings.integrations.backup")}>
              <span className="text-xs text-muted-foreground">{when(h.backup?.last_at)}</span>
            </Row>
          </div>
        )}
      </CardState>
    </div>
  )
}

function SecuritySection() {
  const { t } = useI18n()
  const health = useApi(() => getHealth(), [])
  const [token, setToken] = useState("")
  // localStorage restore is only possible post-mount (hydration boundary).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setToken(getApiToken()), [])

  const save = () => {
    setApiToken(token.trim())
    toast.success(t("settings.security.tokenSaved"))
  }

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader icon={<ShieldCheck className="h-4 w-4 text-primary" aria-hidden />} title={t("settings.security.title")} />
      <div className="space-y-3 p-4">
        <p className="text-sm text-muted-foreground">{t("settings.security.desc")}</p>
        <p className={`text-xs font-semibold ${health.data?.auth_enabled ? "status-good" : "text-muted-foreground"}`}>
          {health.data?.auth_enabled ? t("settings.security.tokenActive") : t("settings.security.tokenInactive")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <label className="min-w-[220px] flex-1">
            <span className="sr-only">{t("settings.security.tokenLabel")}</span>
            <Input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={t("settings.security.tokenLabel")}
              autoComplete="off"
              className="h-9 font-mono text-sm"
            />
          </label>
          <button
            type="button" onClick={save}
            className="rounded-md border border-primary/30 bg-primary/10 px-4 py-2 text-xs font-semibold text-primary hover:bg-primary/20"
          >
            {t("common.save")}
          </button>
        </div>
      </div>
    </div>
  )
}

function DataSection() {
  const { t } = useI18n()
  const [recatBusy, setRecatBusy] = useState(false)
  const urls = exportUrls()

  const runRecategorize = async () => {
    setRecatBusy(true)
    try {
      const result = await recategorize("missing")
      toast.success(t("settings.recategorize.done", { updated: result.items_updated ?? 0 }))
    } catch (err) {
      toast.error(errorDetail(err) || t("common.error"))
    } finally {
      setRecatBusy(false)
    }
  }

  const exportLink = (href: string, label: string) => (
    <a
      href={href} download
      className="flex items-center gap-1.5 rounded-md border border-border bg-secondary/40 px-3 py-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground"
    >
      <Download className="h-3 w-3" aria-hidden /> {label}
    </a>
  )

  return (
    <div className="hud-panel overflow-hidden">
      <PanelHeader icon={<Database className="h-4 w-4 text-primary" aria-hidden />} title={t("settings.data.title")} />
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted-foreground">{t("settings.data.desc")}</p>
        <div className="flex flex-wrap gap-2">
          {exportLink(urls.csv, t("settings.data.csv"))}
          {exportLink(urls.json, t("settings.data.json"))}
          {exportLink(urls.db, t("settings.data.db"))}
        </div>
        <div className="border-t border-border pt-3">
          <Row label={t("settings.recategorize")} hint={t("settings.recategorize.desc")}>
            <button
              type="button" onClick={runRecategorize} disabled={recatBusy}
              className="rounded-md border border-border bg-secondary/40 px-3 py-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground disabled:opacity-50"
            >
              {recatBusy ? "…" : t("settings.recategorize.run")}
            </button>
          </Row>
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-4 sm:p-6 lg:p-8">
      <AppearanceSection />
      <InsightsSection />
      <IntegrationsSection />
      <SecuritySection />
      <DataSection />
    </div>
  )
}
