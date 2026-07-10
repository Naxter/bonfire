"use client"

import { useState } from "react"
import { getMeals, type Meal } from "@/lib/api"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { UtensilsCrossed } from "lucide-react"

const AUDIENCES = [
  { value: "adult", label: "Adults" },
  { value: "toddler", label: "1-year-old" },
  { value: "family", label: "Whole family" },
]

export function MealsCard() {
  const [meals, setMeals] = useState<Meal[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [audience, setAudience] = useState("family")
  const [quick, setQuick] = useState(false)
  const [veg, setVeg] = useState(false)

  const load = async (a = audience, q = quick, v = veg) => {
    setLoading(true)
    try {
      const data = await getMeals({ audience: a, quick: q, vegetarian: v })
      setMeals(data.meals || [])
    } catch {
      setMeals([])
    } finally {
      setLoading(false)
    }
  }

  // Re-fetch when a filter changes, but only after the first load.
  const onAudience = (v: string) => { setAudience(v); if (meals !== null) load(v, quick, veg) }
  const toggleQuick = () => { const nv = !quick; setQuick(nv); if (meals !== null) load(audience, nv, veg) }
  const toggleVeg = () => { const nv = !veg; setVeg(nv); if (meals !== null) load(audience, quick, nv) }

  const chip = (active: boolean, onClick: () => void, label: string) => (
    <button
      onClick={onClick}
      disabled={loading}
      className={`rounded-md border px-2 py-1 text-xs font-medium transition-colors disabled:opacity-50 ${
        active ? "border-primary/40 bg-primary/15 text-primary" : "border-border bg-secondary/40 text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  )

  return (
    <div className="hud-panel flex h-[360px] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-border p-4">
        <div className="flex items-center gap-2">
          <UtensilsCrossed className="h-4 w-4 text-primary" />
          <div className="font-display text-sm font-bold tracking-wide text-foreground">MEAL IDEAS</div>
        </div>
        {meals !== null && (
          <button onClick={() => load()} disabled={loading} className="hud-label text-primary hover:text-foreground disabled:opacity-50">
            {loading ? "…" : "refresh"}
          </button>
        )}
      </div>

      {/* controls */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <Select value={audience} onValueChange={onAudience}>
          <SelectTrigger className="h-8 w-[130px] border-primary/20 bg-secondary/40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AUDIENCES.map((a) => (
              <SelectItem key={a.value} value={a.value} className="text-xs">{a.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        {chip(quick, toggleQuick, "Quick")}
        {chip(veg, toggleVeg, "Veggie")}
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {meals === null ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <p className="text-sm text-muted-foreground">Ideas from what you bought recently.</p>
            <button
              onClick={() => load()}
              disabled={loading}
              className="rounded-md border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/20 disabled:opacity-50"
            >
              {loading ? "Thinking…" : "Suggest meals"}
            </button>
          </div>
        ) : meals.length === 0 ? (
          <div className="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            No ideas yet — buy some fresh ingredients first.
          </div>
        ) : (
          <div className="space-y-3">
            {meals.map((m, i) => (
              <div key={i} className="rounded-md bg-secondary/30 p-3">
                <div className="text-sm font-semibold text-foreground">{m.title}</div>
                {m.uses?.length > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">{m.uses.slice(0, 6).join(" · ")}</div>
                )}
                {m.note && <div className="mt-1 text-xs text-muted-foreground/80">{m.note}</div>}
              </div>
            ))}
            {audience !== "adult" && (
              <p className="pt-1 text-[11px] leading-snug text-muted-foreground/70">
                General guidance for a 1-year-old — always supervise meals, check textures to avoid choking, and watch for allergies. Not medical advice.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
