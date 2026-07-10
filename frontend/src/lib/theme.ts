/**
 * Central design tokens for the dashboard's data visualizations.
 *
 * WHERE THINGS LIVE
 * -----------------
 * - Base UI theme (background, panels, primary/accent, neon, radius, borders):
 *     src/app/globals.css  →  the CSS variables in the `:root, .dark { ... }` block.
 * - Fonts (body + display):
 *     src/app/layout.tsx   →  the next/font imports (Inter + Manrope). Swap those
 *                             two lines to change fonts app-wide.
 * - Chart / store / category colors (what recharts needs as explicit values):
 *     THIS FILE. Edit here and every chart + badge updates.
 */

// --- Store accent colors (badges, bars, chart series) ---
// Muted but still clearly distinct from each other (slate-blue vs dusty rose).
export const STORE_COLORS: Record<string, string> = {
  REWE: "#6b8cae",   // slate blue
  DM: "#b98a8a",     // dusty rose
  Other: "#8f86b5",  // muted lavender
};

// Colors handed to stores without a fixed color (e.g. Aldi/Lidl from a photo).
// Muted, ordered so consecutive stores get clearly different hues.
export const STORE_PALETTE = [
  "#c9a978", // gold
  "#7d9bb5", // slate-blue
  "#bd8fa6", // mauve
  "#7aa07a", // sage
  "#c08f6f", // terracotta
  "#a891b5", // lavender
  "#6fa3a0", // teal
  "#8fa981", // olive-sage
  "#8b95a1", // grey
];

// Stable per-store assignment: the Nth new store gets STORE_PALETTE[N], so any
// two stores always differ (up to the palette size). Seeded from /stores.
const _assigned = new Map<string, string>();
let _nextIdx = 0;

/** Register stores (in canonical order) so each gets a distinct, stable color. */
export function registerStores(names: string[]): void {
  for (const name of names) {
    if (!name || STORE_COLORS[name] || _assigned.has(name)) continue;
    _assigned.set(name, STORE_PALETTE[_nextIdx % STORE_PALETTE.length]);
    _nextIdx++;
  }
}

/** Fallback hash for a store not yet registered (e.g. before /stores loads). */
function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** Resolve a store's color by name. Fixed stores use their set color; others use
 *  their registered (distinct) color, falling back to a stable hash. */
export function storeColor(name: string, index = 0): string {
  if (STORE_COLORS[name]) return STORE_COLORS[name];
  const assigned = _assigned.get(name);
  if (assigned) return assigned;
  return STORE_PALETTE[hashString(name || String(index)) % STORE_PALETTE.length];
}

// --- Category colors for the pie chart (muted, harmonious) ---
export const CATEGORY_COLORS: Record<string, string> = {
  "Obst & Gemüse": "#7fa37a",             // sage
  "Molkereiprodukte & Eier": "#c9a978",   // muted gold
  "Fleisch, Fisch & Veggie": "#b98a8a",   // dusty rose
  "Backwaren": "#c69a6d",                 // tan
  "Tiefkühlprodukte": "#7d9bb5",          // soft blue
  "Nährmittel & Vorrat": "#9a8fb5",       // muted lavender
  "Gewürze, Saucen & Öle": "#c08f6f",     // terracotta
  "Konserven & Fertiggerichte": "#94a3ad",// blue-grey
  "Süßwaren & Snacks": "#bd8fa6",         // mauve
  "Getränke": "#6fa3a0",                  // muted teal
  "Haushalt & Non-Food": "#8aa0a8",       // grey-teal
  "Drogerie & Kosmetik": "#a891b5",       // soft purple
  "Gutscheine & Rabatte": "#8fa981",      // olive-sage
  "Pfand": "#a7ab7f",                     // muted olive
  "Sonstiges": "#8b95a1",                 // neutral grey
  "Uncategorized": "#8b95a1",
};

export const CATEGORY_FALLBACK = ["#7fa37a", "#7d9bb5", "#c9a978", "#b98a8a", "#9a8fb5", "#6fa3a0", "#c08f6f"];

/** Resolve a category's color, falling back by index. */
export function categoryColor(name: string, index = 0): string {
  return CATEGORY_COLORS[name] ?? CATEGORY_FALLBACK[index % CATEGORY_FALLBACK.length];
}

// --- Shared chart chrome ---
export const CHART = {
  axis: "#7b8794",                    // muted axis tick labels
  grid: "rgba(150,170,190,0.10)",     // faint neutral grid lines
  line: "#7aa07a",                    // primary line/dot color (sage)
  lineFrom: "#6b8cae",                // line gradient start (slate blue)
  lineTo: "#7aa07a",                  // line gradient end (sage)
  lineActive: "#8cb08c",              // active dot
  pieStroke: "#141b26",               // gap between pie slices (page bg)
} as const;
