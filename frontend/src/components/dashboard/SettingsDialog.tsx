"use client"

import { useEffect, useState } from "react"
import axios from "axios"
import {
  getMealProfiles, getSettings, updateSettings,
  type AppSettings, type MealProfile,
} from "@/lib/api"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Settings } from "lucide-react"
import { toast } from "sonner"

function NumberField({ label, value, min, max, step = 1, onChange }: {
  label: string; value: number; min: number; max: number; step?: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="hud-label">{label}</span>
      <Input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-8 text-xs"
      />
    </label>
  )
}

export function SettingsDialog() {
  const [open, setOpen] = useState(false)
  const [values, setValues] = useState<AppSettings | null>(null)
  const [profiles, setProfiles] = useState<MealProfile[]>([])
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    getSettings().then(setValues).catch(() => toast.error("Couldn't load settings."))
    getMealProfiles().then(setProfiles).catch(() => setProfiles([]))
  }, [open])

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) =>
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev))

  const save = async () => {
    if (!values) return
    setSaving(true)
    try {
      await updateSettings(values)
      toast.success("Settings saved — reloading…")
      setTimeout(() => window.location.reload(), 800)
    } catch (err) {
      const data = axios.isAxiosError(err) ? (err.response?.data as { detail?: string } | undefined) : undefined
      toast.error(data?.detail || "Saving failed.")
      setSaving(false)
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        title="Settings"
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-secondary/40 text-muted-foreground transition-colors hover:text-foreground"
      >
        <Settings className="h-3.5 w-3.5" />
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-[440px]">
          <DialogHeader>
            <DialogTitle>Settings</DialogTitle>
            <DialogDescription>
              Behavior preferences, applied immediately. Credentials, ports and
              schedules live in <code>.env</code> on the server.
            </DialogDescription>
          </DialogHeader>

          {values && (
            <div className="space-y-5">
              <fieldset className="space-y-2">
                <div className="font-display text-xs font-bold tracking-wide text-foreground">MEAL IDEAS</div>
                <div className="grid grid-cols-2 gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="hud-label">Default profile</span>
                    <Select value={values["meals.profile"]} onValueChange={(v) => set("meals.profile", v)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {profiles.map((p) => (
                          <SelectItem key={p.key} value={p.key} className="text-xs">{p.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </label>
                  <NumberField label="Ideas per run" value={values["meals.count"]} min={1} max={6}
                               onChange={(v) => set("meals.count", v)} />
                  <label className="flex flex-col gap-1">
                    <span className="hud-label">Ingredient context</span>
                    <Select value={values["meals.context"]}
                            onValueChange={(v) => set("meals.context", v as AppSettings["meals.context"])}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="trip" className="text-xs">Latest trip per store</SelectItem>
                        <SelectItem value="days" className="text-xs">Rolling window</SelectItem>
                      </SelectContent>
                    </Select>
                  </label>
                  <NumberField label="Window (days)" value={values["meals.days"]} min={3} max={60}
                               onChange={(v) => set("meals.days", v)} />
                </div>
              </fieldset>

              <fieldset className="space-y-2">
                <div className="font-display text-xs font-bold tracking-wide text-foreground">RESTOCK RADAR</div>
                <div className="grid grid-cols-2 gap-3">
                  <NumberField label="Due within (days)" value={values["restock.horizon_days"]} min={1} max={14}
                               onChange={(v) => set("restock.horizon_days", v)} />
                  <NumberField label="Min. purchases" value={values["restock.min_purchases"]} min={2} max={10}
                               onChange={(v) => set("restock.min_purchases", v)} />
                </div>
              </fieldset>

              <fieldset className="space-y-2">
                <div className="font-display text-xs font-bold tracking-wide text-foreground">BUDGET FORECAST</div>
                <div className="grid grid-cols-2 gap-3">
                  <NumberField label="History (months)" value={values["budget.history_months"]} min={2} max={24}
                               onChange={(v) => set("budget.history_months", v)} />
                  <NumberField label="Anomaly factor" value={values["budget.anomaly_factor"]} min={1.1} max={5}
                               step={0.1} onChange={(v) => set("budget.anomaly_factor", v)} />
                </div>
              </fieldset>
            </div>
          )}

          <DialogFooter>
            <button
              onClick={save}
              disabled={saving || !values}
              className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
