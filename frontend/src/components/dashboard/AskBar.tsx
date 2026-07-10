"use client"

import { useState } from "react"
import { ask, type AskResponse } from "@/lib/api"
import { Sparkles } from "lucide-react"

// Minimal markdown for LLM answers — **bold**, *italic*, `code`, "- " bullets.
// Built as React nodes (no dangerouslySetInnerHTML, so no XSS surface).
function inline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  const re = /\*\*(.+?)\*\*|\*([^*\n]+?)\*|`([^`\n]+?)`/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    if (m[1] !== undefined) {
      nodes.push(<strong key={nodes.length} className="font-semibold">{m[1]}</strong>)
    } else if (m[2] !== undefined) {
      nodes.push(<em key={nodes.length}>{m[2]}</em>)
    } else {
      nodes.push(<code key={nodes.length} className="rounded bg-secondary/60 px-1 font-mono text-[0.85em]">{m[3]}</code>)
    }
    last = m.index + m[0].length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function Answer({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  let bullets: string[] = []
  const flush = () => {
    if (!bullets.length) return
    blocks.push(
      <ul key={blocks.length} className="list-disc space-y-0.5 pl-5">
        {bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}
      </ul>
    )
    bullets = []
  }
  for (const line of text.split(/\r?\n/)) {
    const bullet = line.match(/^\s*[-*•]\s+(.*)/)
    if (bullet) { bullets.push(bullet[1]); continue }
    flush()
    if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line)}</p>)
  }
  flush()
  return <div className="space-y-1.5 text-foreground">{blocks}</div>
}

export function AskBar() {
  const [q, setQ] = useState("")
  const [loading, setLoading] = useState(false)
  const [res, setRes] = useState<AskResponse | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!q.trim() || loading) return
    setLoading(true)
    setRes(null)
    try {
      setRes(await ask(q.trim()))
    } catch {
      setRes({ question: q, error: "Request failed — is the backend reachable?" })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="hud-panel p-4">
      <form onSubmit={submit} className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 shrink-0 text-primary" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask your groceries…  e.g. “how much did I spend on drinks last month?”"
          className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
        <button
          type="submit"
          disabled={loading || !q.trim()}
          className="rounded-md border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
        >
          {loading ? "Thinking…" : "Ask"}
        </button>
      </form>

      {res && (
        <div className="mt-3 border-t border-border pt-3 text-sm">
          {res.error ? (
            <span className="text-muted-foreground">{res.error}</span>
          ) : (
            <div className="space-y-1">
              {res.answer ? <Answer text={res.answer} /> : <p className="text-foreground">No answer.</p>}
              {res.rows && (
                <p className="hud-label truncate">
                  query · {res.rows.length} row{res.rows.length === 1 ? "" : "s"}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
