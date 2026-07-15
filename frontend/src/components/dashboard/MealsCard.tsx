"use client"

import { useEffect, useRef, useState } from "react"
import {
  createMealProfile, deleteMealProfile, getMealProfiles, getMeals, getSettings,
  updateMealProfile, type MealProfile, type MealsResponse,
} from "@/lib/api"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Pencil, UtensilsCrossed } from "lucide-react"

const NEW_PROFILE = "__new__"
const LOADING_PHASES = ["Checking the pantry…", "Asking the chef…", "Plating up…"]

type UiState = "idle" | "loading" | "done" | "http_error"

export function MealsCard() {
  const [profiles, setProfiles] = useState<MealProfile[]>([])
  const [profileKey, setProfileKey] = useState("family")
  const [count, setCount] = useState(3)
  const [quick, setQuick] = useState(false)
  const [veg, setVeg] = useState(false)
  const [context, setContext] = useState<"trip" | "days">("trip")
  const [days, setDays] = useState(14)
  const [result, setResult] = useState<MealsResponse | null>(null)
  const [ui, setUi] = useState<UiState>("idle")
  const [phase, setPhase] = useState(0)
  const seq = useRef(0)

  // profile editor dialog
  const [editorOpen, setEditorOpen] = useState(false)
  const [editing, setEditing] = useState<MealProfile | null>(null) // null = create
  const [draftName, setDraftName] = useState("")
  const [draftPrompt, setDraftPrompt] = useState("")
  const [editorError, setEditorError] = useState("")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getMealProfiles().then(setProfiles).catch(() => setProfiles([]))
    // Card defaults come from the settings dialog; ad-hoc changes stay local.
    getSettings().then((s) => {
      setProfileKey(s["meals.profile"])
      setCount(s["meals.count"])
      setContext(s["meals.context"])
      setDays(s["meals.days"])
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (ui !== "loading") return
    const t = setInterval(() => setPhase((p) => (p + 1) % LOADING_PHASES.length), 2500)
    return () => clearInterval(t)
  }, [ui])

  const generate = async () => {
    const mySeq = ++seq.current
    setUi("loading")
    setPhase(0)
    try {
      const avoid = result?.meals.map((m) => m.title) ?? []
      const data = await getMeals({ profile: profileKey, count, quick, vegetarian: veg, context, days, avoid })
      if (mySeq !== seq.current) return // a newer request superseded this one
      setResult(data)
      setUi("done")
    } catch {
      if (mySeq !== seq.current) return
      setUi("http_error")
    }
  }

  const openEditor = (p: MealProfile | null) => {
    setEditing(p)
    setDraftName(p?.name ?? "")
    setDraftPrompt(p?.prompt ?? "")
    setEditorError("")
    setEditorOpen(true)
  }

  const saveProfile = async () => {
    if (!draftName.trim() || !draftPrompt.trim()) {
      setEditorError("Name and prompt are both required.")
      return
    }
    setSaving(true)
    setEditorError("")
    try {
      if (editing) {
        await updateMealProfile(editing.id, draftName.trim(), draftPrompt.trim())
      } else {
        const created = await createMealProfile(draftName.trim(), draftPrompt.trim())
        setProfileKey(created.key)
      }
      setProfiles(await getMealProfiles())
      setEditorOpen(false)
    } catch {
      setEditorError("Saving failed — is the backend reachable?")
    } finally {
      setSaving(false)
    }
  }

  const removeProfile = async () => {
    if (!editing || editing.is_builtin) return
    if (!window.confirm(`Delete the profile "${editing.name}"?`)) return
    setSaving(true)
    try {
      await deleteMealProfile(editing.id)
      if (profileKey === editing.key) setProfileKey("family")
      setProfiles(await getMealProfiles())
      setEditorOpen(false)
    } catch {
      setEditorError("Deleting failed.")
    } finally {
      setSaving(false)
    }
  }

  const currentProfile = profiles.find((p) => p.key === profileKey)

  const chip = (active: boolean, onClick: () => void, label: string, title?: string) => (
    <button
      onClick={onClick}
      disabled={ui === "loading"}
      title={title}
      className={`rounded-md border px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
        active ? "border-primary/40 bg-primary/15 text-primary" : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="hud-panel flex h-[420px] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-border p-4">
        <div className="flex items-center gap-2">
          <UtensilsCrossed className="h-4 w-4 text-primary" />
          <div className="font-display text-sm font-bold tracking-wide text-foreground">MEAL IDEAS</div>
        </div>
        {result?.context && (
          <span className="hud-label text-muted-foreground/70" title={`Ingredients from ${result.context.label}`}>
            {result.context.mode === "trip" ? (result.context.widened ? "trip+" : "last trip") : "window"}
          </span>
        )}
      </div>

      {/* controls */}
      <div className="space-y-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <Select
            value={profileKey}
            onValueChange={(v) => (v === NEW_PROFILE ? openEditor(null) : setProfileKey(v))}
          >
            <SelectTrigger className="h-8 flex-1 border-primary/20 bg-secondary/40 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {profiles.map((p) => (
                <SelectItem key={p.key} value={p.key} className="text-xs">{p.name}</SelectItem>
              ))}
              <SelectItem value={NEW_PROFILE} className="text-xs text-primary">＋ New profile…</SelectItem>
            </SelectContent>
          </Select>
          <button
            onClick={() => currentProfile && openEditor(currentProfile)}
            disabled={!currentProfile}
            title="Edit this profile's prompt"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-secondary/40 text-muted-foreground hover:text-foreground disabled:opacity-40"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {chip(quick, () => setQuick(!quick), "Quick")}
          {chip(veg, () => setVeg(!veg), "Veggie")}
          {chip(context === "trip", () => setContext(context === "trip" ? "days" : "trip"),
            context === "trip" ? "Last trip" : `${days} days`,
            "Ingredient context: your latest shopping trip per store, or a rolling window")}
          <div className="ml-auto">
            <Select value={String(count)} onValueChange={(v) => setCount(Number(v))}>
              <SelectTrigger className="h-7 w-[88px] border-border bg-secondary/40 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <SelectItem key={n} value={String(n)} className="text-xs">
                    {n} idea{n > 1 ? "s" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* content */}
      <div className="flex-1 overflow-y-auto p-4">
        {ui === "idle" && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <p className="text-sm text-muted-foreground">
              Ideas from what&apos;s already in the house — nothing happens until you ask.
            </p>
          </div>
        )}

        {ui === "loading" && (
          <div className="space-y-3">
            <p className="text-center text-xs text-muted-foreground">{LOADING_PHASES[phase]}</p>
            {Array.from({ length: Math.min(count, 3) }).map((_, i) => (
              <div key={i} className="animate-pulse rounded-md bg-secondary/30 p-3">
                <div className="h-3.5 w-2/5 rounded bg-secondary/80" />
                <div className="mt-2 h-2.5 w-4/5 rounded bg-secondary/60" />
              </div>
            ))}
          </div>
        )}

        {ui === "http_error" && (
          <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            Couldn&apos;t reach the kitchen — request failed or was rate-limited. Try again in a minute.
          </div>
        )}

        {ui === "done" && result?.status === "llm_error" && (
          <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            The LLM didn&apos;t answer — provider error, not an empty pantry. Try again shortly.
          </div>
        )}

        {ui === "done" && result?.status === "no_ingredients" && (
          <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            No recent food purchases to cook from — import some receipts first.
          </div>
        )}

        {ui === "done" && result?.status === "ok" && result.meals.length === 0 && (
          <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            Nothing came back — try fewer constraints or another profile.
          </div>
        )}

        {ui === "done" && result?.status === "ok" && result.meals.length > 0 && (
          <div className="grid gap-3 sm:grid-cols-2">
            {result.meals.map((m, i) => (
              <div key={i} className="rounded-md bg-secondary/30 p-3">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-sm font-semibold text-foreground">{m.title}</div>
                  {m.time_minutes ? (
                    <span className="hud-label shrink-0 text-muted-foreground/70">~{m.time_minutes} min</span>
                  ) : null}
                </div>
                {m.uses?.length > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {m.uses.slice(0, 6).join(" · ")}
                    {m.uses.length > 6 && ` · +${m.uses.length - 6} more`}
                  </div>
                )}
                {m.missing && m.missing.length > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground/90">
                    <span className="text-primary/80">still needed:</span> {m.missing.slice(0, 5).join(", ")}
                  </div>
                )}
                {m.note && <div className="mt-1 text-xs text-muted-foreground/80">{m.note}</div>}
                {m.adaptation && (
                  <div className="mt-1 text-xs italic text-muted-foreground/80">
                    {m.adaptation}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* generate — always visible, never auto-fired */}
      <div className="border-t border-border p-3">
        <button
          onClick={generate}
          disabled={ui === "loading"}
          className="w-full rounded-md border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
        >
          {ui === "loading" ? "Thinking…" : result ? "Suggest again" : "Suggest meals"}
        </button>
      </div>

      {/* profile editor */}
      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editing ? `Edit “${editing.name}”` : "New meal profile"}</DialogTitle>
            <DialogDescription>
              This text steers the suggestions. Your groceries, the Quick/Veggie
              constraints and the output format are added automatically.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              value={draftName}
              onChange={(e) => setDraftName(e.target.value)}
              placeholder="Name, e.g. Meal-prep Sunday"
              maxLength={60}
            />
            <Textarea
              value={draftPrompt}
              onChange={(e) => setDraftPrompt(e.target.value)}
              placeholder="Instructions for the cook, e.g. High-protein dinners, no pork, everything freezable…"
              rows={8}
              maxLength={4000}
            />
            {editing?.is_builtin && (
              <p className="text-xs text-muted-foreground">
                Built-in profile: the prompt is yours to edit, but it can&apos;t be deleted.
              </p>
            )}
            {editorError && <p className="text-xs text-destructive">{editorError}</p>}
          </div>
          <DialogFooter className="gap-2 sm:justify-between">
            {editing && !editing.is_builtin ? (
              <button
                onClick={removeProfile}
                disabled={saving}
                className="rounded-md border border-destructive/40 px-3 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 disabled:opacity-50"
              >
                Delete
              </button>
            ) : <span />}
            <button
              onClick={saveProfile}
              disabled={saving}
              className="rounded-md border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
