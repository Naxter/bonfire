"use client"

import { useTheme } from "next-themes"
import { useEffect, useState } from "react"
import { CHART_THEMES, type ChartChrome } from "./theme"

/** The active theme's chart chrome. Falls back to dark until mounted
 *  (next-themes resolves the theme only on the client). */
export function useChartTheme(): ChartChrome {
  const { resolvedTheme, theme } = useTheme()
  const [mounted, setMounted] = useState(false)
  // Hydration boundary: the resolved theme exists only on the client.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), [])
  if (!mounted) return CHART_THEMES.dark
  const key = theme === "hc" ? "hc" : resolvedTheme === "light" ? "light" : "dark"
  return CHART_THEMES[key] ?? CHART_THEMES.dark
}
