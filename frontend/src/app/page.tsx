"use client"

import {useEffect, useMemo, useState} from "react"
import {OverviewChart} from "@/components/dashboard/OverviewChart"
import {RecentReceipts} from "@/components/dashboard/RecentReceipts"
import {CategoryPie} from "@/components/dashboard/CategoryPie"
import {AskBar} from "@/components/dashboard/AskBar"
import {RestockCard} from "@/components/dashboard/RestockCard"
import {BudgetCard} from "@/components/dashboard/BudgetCard"
import {MealsCard} from "@/components/dashboard/MealsCard"
import {UploadReceiptButton} from "@/components/dashboard/UploadReceiptButton"
import {TimeRange, DEFAULT_RANGE, type Range} from "@/components/dashboard/TimeRange"
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from "@/components/ui/select"
import {ScrollArea} from "@/components/ui/scroll-area"
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from "@/components/ui/table"
import {
    getDashboardStats,
    getMonthlyData,
    getCategoryData,
    getTopProducts,
    getPriceVolatility,
    getPriceHistory, getWalletShare, getStores, getHealth, type Health
} from "@/lib/api"
import Image from "next/image"
import {
    Euro, TrendingUp, Package, AlertTriangle,
    LineChart as LineChartIcon, Activity, Boxes, Zap, Search, X
} from "lucide-react"

import {LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer} from "recharts"
import {storeColor, registerStores, CHART} from "@/lib/theme"

export default function DashboardPage() {
    // --- State ---
    const [stats, setStats] = useState<any>(null)
    const [monthlyData, setMonthlyData] = useState([])
    const [categoryData, setCategoryData] = useState([])
    const [topProducts, setTopProducts] = useState<any[]>([])

    // Price Volatility & History State
    const [volatilityData, setVolatilityData] = useState<any[]>([])
    const [selectedItem, setSelectedItem] = useState<string | null>(null)
    const [priceHistoryData, setPriceHistoryData] = useState<any[]>([])

    // Global filters
    const [globalStore, setGlobalStore] = useState("all")
    const [range, setRange] = useState<Range>(DEFAULT_RANGE)
    const [category, setCategory] = useState("all")

    // Client-side search boxes
    const [prodQuery, setProdQuery] = useState("")
    const [volaQuery, setVolaQuery] = useState("")

    const [walletShareData, setWalletShareData] = useState<any[]>([])
    const [stores, setStores] = useState<{ key: string; display_name: string }[]>([])
    const [health, setHealth] = useState<Health | null>(null)

    const toggleCategory = (name: string) => setCategory((prev) => (prev === name ? "all" : name))

    // Load the available stores once (drives the dropdown + distinct colors).
    useEffect(() => {
        getStores().then((s) => {
            registerStores(s.map((x) => x.display_name))
            setStores(s)
        }).catch((e) => console.error("Failed to fetch stores", e))
    }, [])

    // Poll backend health for the status badge.
    useEffect(() => {
        const load = () =>
            getHealth()
                .then(setHealth)
                .catch(() => setHealth({status: "degraded", db: false, llm_provider: "unreachable", llm_configured: false}))
        load()
        const t = setInterval(load, 30000)
        return () => clearInterval(t)
    }, [])

    // --- Global Data Load (store-scoped; time-independent overview) ---
    useEffect(() => {
        const loadGlobalData = async () => {
            try {
                const [statsRes, monthlyRes, volRes] = await Promise.all([
                    getDashboardStats(globalStore),
                    getMonthlyData(globalStore),
                    getPriceVolatility(globalStore),
                ])
                setStats(statsRes)
                setMonthlyData(monthlyRes)
                setVolatilityData(volRes)
                if (volRes && volRes.length > 0) {
                    setSelectedItem(volRes[0].name)
                } else {
                    setSelectedItem(null)
                    setPriceHistoryData([])
                }
            } catch (error) {
                console.error("Failed to fetch global data", error)
            }
        }
        loadGlobalData()
    }, [globalStore])

    // --- Category breakdown (store + time range) ---
    useEffect(() => {
        getCategoryData({store: globalStore, start: range.start, end: range.end})
            .then(setCategoryData)
            .catch((error) => console.error("Failed to fetch categories", error))
    }, [globalStore, range.start, range.end])

    // --- Top products (store + time range + category) ---
    useEffect(() => {
        getTopProducts({store: globalStore, start: range.start, end: range.end, category})
            .then(setTopProducts)
            .catch((error) => console.error("Failed to fetch top products", error))
    }, [globalStore, range.start, range.end, category])

    // --- Price History Load ---
    useEffect(() => {
        if (!selectedItem) {
            setPriceHistoryData([])
            return
        }
        const fetchHistory = async () => {
            try {
                const res = await getPriceHistory(selectedItem, globalStore)
                setPriceHistoryData(res)
            } catch (error) {
                console.error("Failed to fetch price history", error)
            }
        }
        fetchHistory()
    }, [selectedItem, globalStore])

    // Load Wallet Share on initial mount
    useEffect(() => {
        const fetchWallet = async () => {
            const res = await getWalletShare()
            setWalletShareData(res)
        }
        fetchWallet()
    }, [])

    const filteredProducts = useMemo(
        () => topProducts.filter((p) => p.name?.toLowerCase().includes(prodQuery.toLowerCase())),
        [topProducts, prodQuery]
    )
    const filteredVolatility = useMemo(
        () => volatilityData.filter((v) => v.name?.toLowerCase().includes(volaQuery.toLowerCase())),
        [volatilityData, volaQuery]
    )

    if (!stats) return (
        <div className="flex h-screen items-center justify-center">
            <div className="flex items-center gap-3 hud-label text-primary">
                <span className="h-2.5 w-2.5 rounded-full bg-primary pulse-dot"/> Initializing dashboard…
            </div>
        </div>
    )

    const biggestHike = volatilityData.length > 0 ? volatilityData[0] : null
    const allTimeSpend = walletShareData.reduce((s: number, x: any) => s + (x.value || 0), 0)
    const shareColor = storeColor
    const up = stats.diff_percent >= 0

    // Custom Tooltip for the Price Line Chart
    const PriceTooltip = ({active, payload}: any) => {
        if (active && payload && payload.length) {
            return (
                <div className="rounded-lg border border-border bg-popover/95 p-3 shadow-[0_8px_24px_-10px_rgba(0,0,0,0.6)] backdrop-blur">
                    <p className="text-sm font-semibold mb-1">{payload[0].payload.exact_date}</p>
                    <p className="text-sm neon-text font-bold">€{payload[0].value.toFixed(2)}</p>
                </div>
            )
        }
        return null
    }

    return (
        <div className="flex min-h-screen flex-col">
            {/* ===== HEADER ===== */}
            {/* min-h + flex-wrap: on narrow screens the controls wrap onto a
                second row instead of pushing the store select off-screen. */}
            <header className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border bg-background/70 px-4 py-2 backdrop-blur-xl sm:px-6">
                <div className="flex items-center gap-3">
                    <Image src="/logo.png" alt="Bonfire" width={36} height={36}
                           className="h-9 w-9 rounded-lg border border-primary/40 glow-cyan"/>
                    <div className="leading-tight">
                        <div className="font-display text-sm font-bold tracking-[0.2em] text-foreground">BONFIRE</div>
                        <div className="hud-label">Unified receipt intelligence</div>
                    </div>
                </div>

                <div className="ml-auto flex items-center gap-3 sm:gap-4">
                    {(() => {
                        const ok = health?.status === "ok"
                        const down = health ? !health.db : false
                        const dot = !health
                            ? "bg-muted-foreground"
                            : ok
                                ? "bg-primary pulse-dot"
                                : down
                                    ? "bg-rose-500"
                                    : "bg-amber-400"
                        const label = !health ? "…" : ok ? "Live" : down ? "Offline" : "Degraded"
                        const tip = health
                            ? `LLM: ${health.llm_provider}${health.llm_configured ? "" : " (not configured)"} · DB ${health.db ? "ok" : "down"}`
                            : "Checking backend…"
                        return (
                            <div className="hidden items-center gap-2 md:flex" title={tip}>
                                <span className={`h-2 w-2 rounded-full ${dot}`}/>
                                <span className={`hud-label ${ok ? "text-primary" : down ? "text-rose-400" : health ? "text-amber-400" : ""}`}>{label}</span>
                            </div>
                        )
                    })()}
                    <UploadReceiptButton/>
                    <div className="flex items-center gap-2">
                        <span className="hud-label hidden sm:inline">Store</span>
                        <Select value={globalStore} onValueChange={setGlobalStore}>
                            <SelectTrigger className="w-[130px] h-8 bg-secondary/60 border-primary/20 text-xs">
                                <SelectValue placeholder="All Stores"/>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">All Stores</SelectItem>
                                {stores.map((s) => (
                                    <SelectItem key={s.key} value={s.key}>{s.display_name}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </header>

            <main className="flex-1 space-y-5 p-6 lg:p-8">
                {/* ===== OVERVIEW + GLOBAL TIME RANGE ===== */}
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <h2 className="font-display text-2xl font-bold tracking-widest text-foreground">OVERVIEW</h2>
                    <div className="flex flex-wrap items-center gap-2">
                        {category !== "all" && (
                            <button
                                type="button"
                                onClick={() => setCategory("all")}
                                className="flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary transition-colors hover:bg-primary/20"
                                title="Clear category filter"
                            >
                                {category} <X className="h-3 w-3"/>
                            </button>
                        )}
                        <TimeRange value={range} onChange={setRange}/>
                    </div>
                </div>

                {/* ===== ASK BAR ===== */}
                <AskBar/>

                {/* ===== KPI STRIP ===== */}
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    {/* Total this month */}
                    <div className="hud-panel hud-corners p-5">
                        <div className="flex items-center justify-between">
                            <span className="hud-label">Spent · recent month</span>
                            <Euro className="h-4 w-4 text-primary"/>
                        </div>
                        <div className="mt-3 font-display text-3xl font-bold neon-text">€{stats.current_month_total?.toFixed(2) || "0.00"}</div>
                        <p className="mt-2 flex items-center gap-1 text-xs">
                            <TrendingUp className={`h-3.5 w-3.5 ${up ? "text-emerald-400" : "text-rose-400 rotate-180"}`}/>
                            <span className={up ? "text-emerald-400 font-semibold" : "text-rose-400 font-semibold"}>
                                {up ? "+" : ""}{stats.diff_percent}%
                            </span>
                            <span className="text-muted-foreground">vs previous</span>
                        </p>
                    </div>

                    {/* All-time spend */}
                    <div className="hud-panel hud-corners p-5">
                        <div className="flex items-center justify-between">
                            <span className="hud-label">All-time spend</span>
                            <Activity className="h-4 w-4 text-primary"/>
                        </div>
                        <div className="mt-3 font-display text-3xl font-bold neon-text">€{allTimeSpend.toFixed(0)}</div>
                        <p className="mt-2 text-xs text-muted-foreground">across {walletShareData.length || 0} store{walletShareData.length === 1 ? "" : "s"}</p>
                    </div>

                    {/* Highest hike */}
                    <div className="hud-panel hud-corners p-5">
                        <div className="flex items-center justify-between">
                            <span className="hud-label">Highest price hike</span>
                            <AlertTriangle className="h-4 w-4 text-rose-400"/>
                        </div>
                        {biggestHike ? (
                            <>
                                <div className="mt-3 truncate font-display text-xl font-bold text-rose-300" title={biggestHike.name}>{biggestHike.name}</div>
                                <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-rose-400">
                                    <TrendingUp className="h-3.5 w-3.5"/> +{biggestHike.change_percent}%
                                    <span className="ml-1 font-normal text-muted-foreground">€{biggestHike.min_price} → €{biggestHike.max_price}</span>
                                </p>
                            </>
                        ) : (
                            <div className="mt-3 text-sm text-muted-foreground">Not enough history yet.</div>
                        )}
                    </div>

                    {/* Tracked items */}
                    <div className="hud-panel hud-corners p-5">
                        <div className="flex items-center justify-between">
                            <span className="hud-label">Tracked products</span>
                            <Boxes className="h-4 w-4 text-primary"/>
                        </div>
                        <div className="mt-3 font-display text-3xl font-bold neon-text">{volatilityData.length}</div>
                        <p className="mt-2 text-xs text-muted-foreground">with repeat purchases</p>
                    </div>
                </div>

                {/* ===== DAILY ASSISTANT ===== */}
                <div className="grid gap-4 lg:grid-cols-3">
                    <RestockCard/>
                    <BudgetCard/>
                    <MealsCard/>
                </div>

                {/* ===== WALLET SHARE BAR ===== */}
                {walletShareData.length > 0 && (
                    <div className="hud-panel p-5">
                        <div className="mb-3 flex items-center gap-2">
                            <Zap className="h-4 w-4 text-primary"/>
                            <span className="hud-label">Wallet share</span>
                        </div>
                        <div className="flex h-3 w-full overflow-hidden rounded-full border border-border bg-secondary/40">
                            {walletShareData.map((s: any, i: number) => {
                                const pct = allTimeSpend ? (s.value / allTimeSpend) * 100 : 0
                                const c = shareColor(s.name, i)
                                return (
                                    <div key={s.name} style={{width: `${pct}%`, background: c}} title={`${s.name}: €${s.value.toFixed(2)}`}/>
                                )
                            })}
                        </div>
                        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
                            {walletShareData.map((s: any, i: number) => {
                                const pct = allTimeSpend ? (s.value / allTimeSpend) * 100 : 0
                                const c = shareColor(s.name, i)
                                return (
                                    <div key={s.name} className="flex items-center gap-2">
                                        <span className="h-2.5 w-2.5 rounded-full" style={{background: c}}/>
                                        <span className="text-xs text-muted-foreground uppercase tracking-wider">{s.name}</span>
                                        <span className="text-xs font-bold text-foreground">{pct.toFixed(0)}%</span>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                )}

                {/* ===== INFLATION TRACKER ===== */}
                <div className="hud-panel overflow-hidden">
                    <div className="flex items-center gap-2 border-b border-border bg-secondary/20 px-5 py-4">
                        <LineChartIcon className="h-5 w-5 text-primary"/>
                        <div>
                            <div className="font-display text-sm font-bold tracking-widest text-foreground">INFLATION TRACKER</div>
                            <div className="hud-label">Select an item to trace its price over time</div>
                        </div>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-3 h-[680px] md:h-[430px] overflow-hidden">
                        {/* Leaderboard */}
                        <div className="col-span-1 flex flex-col border-b border-border md:border-b-0 md:border-r bg-background/20 h-[280px] md:h-full overflow-hidden">
                            <div className="shrink-0 space-y-2 border-b border-border px-3 py-2.5">
                                <div className="hud-label px-1">Most volatile products</div>
                                <div className="relative">
                                    <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"/>
                                    <input
                                        value={volaQuery}
                                        onChange={(e) => setVolaQuery(e.target.value)}
                                        placeholder="Filter items…"
                                        className="h-7 w-full rounded-md border border-primary/20 bg-secondary/40 pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
                                    />
                                </div>
                            </div>
                            <div className="flex-1 overflow-y-auto min-h-0 p-1.5">
                                {filteredVolatility.length === 0 ? (
                                    <div className="py-10 text-center text-xs text-muted-foreground">No items match.</div>
                                ) : filteredVolatility.map((item: any, index: number) => {
                                    const active = selectedItem === item.name
                                    return (
                                        <div
                                            key={index}
                                            className={`flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition-all ${active ? "bg-primary/10 ring-1 ring-primary/40" : "hover:bg-secondary/50"}`}
                                            onClick={() => setSelectedItem(item.name)}
                                        >
                                            <div className="space-y-1 min-w-0">
                                                <div className="font-medium text-sm flex items-center gap-2 truncate">
                                                    <span className="truncate">{item.name}</span>
                                                    <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider"
                                                          style={{background: `${shareColor(item.store, index)}1f`, color: shareColor(item.store, index)}}>
                                                        {item.store}
                                                    </span>
                                                </div>
                                                <div className="text-xs text-muted-foreground">€{item.min_price.toFixed(2)} → €{item.max_price.toFixed(2)}</div>
                                            </div>
                                            <div className="font-bold text-rose-400 shrink-0">+{item.change_percent.toFixed(1)}%</div>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>

                        {/* Line chart */}
                        <div className="col-span-1 md:col-span-2 p-4 md:p-6 flex flex-col h-[400px] md:h-full overflow-hidden">
                            <h3 className="font-display text-base font-bold mb-4 shrink-0 truncate tracking-wider">{selectedItem || "Select a product"}</h3>
                            <div className="flex-1 min-h-0 min-w-0">
                                {priceHistoryData.length > 0 ? (
                                    <ResponsiveContainer width="100%" height="100%">
                                        <LineChart data={priceHistoryData} margin={{top: 5, right: 10, left: -10, bottom: 5}}>
                                            <defs>
                                                <linearGradient id="priceLine" x1="0" y1="0" x2="1" y2="0">
                                                    <stop offset="0%" stopColor={CHART.lineFrom}/>
                                                    <stop offset="100%" stopColor={CHART.lineTo}/>
                                                </linearGradient>
                                            </defs>
                                            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={CHART.grid}/>
                                            <XAxis dataKey="exact_date" stroke={CHART.axis} fontSize={10} tickLine={false} axisLine={false} minTickGap={20}/>
                                            <YAxis stroke={CHART.axis} fontSize={12} tickLine={false} axisLine={false} tickFormatter={(val) => `€${val.toFixed(2)}`} domain={['auto', 'auto']}/>
                                            <Tooltip content={<PriceTooltip/>} cursor={{stroke: 'rgba(122,160,122,0.45)', strokeWidth: 1, strokeDasharray: '4 4'}}/>
                                            <Line
                                                type="monotone"
                                                dataKey="price"
                                                stroke="url(#priceLine)"
                                                strokeWidth={2.5}
                                                dot={{r: 2.5, fill: CHART.line, stroke: "none"}}
                                                activeDot={{r: 6, fill: CHART.lineActive, stroke: CHART.pieStroke, strokeWidth: 2}}
                                                isAnimationActive={false}
                                            />
                                        </LineChart>
                                    </ResponsiveContainer>
                                ) : (
                                    <div className="h-full flex items-center justify-center text-muted-foreground text-sm">No history available.</div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>

                {/* ===== CHARTS ROW ===== */}
                <div className="grid gap-4 lg:grid-cols-7">
                    <div className="hud-panel col-span-1 lg:col-span-4 p-5">
                        <div className="mb-2 flex items-center justify-between">
                            <div className="font-display text-sm font-bold tracking-widest text-foreground">SPENDING HISTORY</div>
                            <span className="hud-label hidden sm:block">All time</span>
                        </div>
                        <OverviewChart data={monthlyData}/>
                    </div>

                    <div className="hud-panel col-span-1 lg:col-span-3 p-5">
                        <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                            <div className="font-display text-sm font-bold tracking-widest text-foreground">TOP CATEGORIES</div>
                            <span className="hud-label">
                                {range.label}{category !== "all" ? ` · ${category}` : ""} · tap a slice to filter
                            </span>
                        </div>
                        <CategoryPie
                            data={categoryData}
                            activeCategory={category === "all" ? null : category}
                            onSelect={toggleCategory}
                        />
                    </div>
                </div>

                {/* ===== LISTS ROW ===== */}
                <div className="grid gap-4 lg:grid-cols-7">
                    <div className="hud-panel col-span-1 lg:col-span-3 flex flex-col h-[600px] overflow-hidden">
                        <div className="flex flex-col gap-2 border-b border-border p-5 sm:flex-row sm:items-center sm:justify-between">
                            <div className="flex items-center gap-2 font-display text-sm font-bold tracking-widest text-foreground">
                                <Package className="h-4 w-4 text-primary"/> MOST BOUGHT
                            </div>
                            <div className="relative w-full sm:w-[190px]">
                                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"/>
                                <input
                                    value={prodQuery}
                                    onChange={(e) => setProdQuery(e.target.value)}
                                    placeholder="Filter products…"
                                    className="h-8 w-full rounded-md border border-primary/20 bg-secondary/40 pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
                                />
                            </div>
                        </div>
                        <div className="flex-1 overflow-hidden">
                            <ScrollArea className="h-full w-full">
                                {topProducts.length === 0 ? (
                                    <div className="py-12 text-center text-sm text-muted-foreground">No data for this period.</div>
                                ) : filteredProducts.length === 0 ? (
                                    <div className="py-12 text-center text-sm text-muted-foreground">No products match “{prodQuery}”.</div>
                                ) : (
                                    <Table>
                                        <TableHeader className="sticky top-0 bg-background/80 backdrop-blur z-10">
                                            <TableRow className="hover:bg-transparent border-border">
                                                <TableHead className="hud-label">Product</TableHead>
                                                <TableHead className="hud-label text-right">Qty</TableHead>
                                            </TableRow>
                                        </TableHeader>
                                        <TableBody>
                                            {filteredProducts.map((item: any, index: number) => (
                                                <TableRow key={index} className="border-border/60 hover:bg-secondary/40">
                                                    <TableCell className="font-medium text-sm flex items-center gap-2">
                                                        {item.name}
                                                        <span className="rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider"
                                                              style={{background: `${shareColor(item.store, index)}1f`, color: shareColor(item.store, index)}}>
                                                            {item.store}
                                                        </span>
                                                    </TableCell>
                                                    <TableCell className="text-right font-mono font-semibold neon-cyan">{item.quantity}</TableCell>
                                                </TableRow>
                                            ))}
                                        </TableBody>
                                    </Table>
                                )}
                            </ScrollArea>
                        </div>
                    </div>

                    <div className="hud-panel col-span-1 lg:col-span-4 flex flex-col h-[600px] overflow-hidden">
                        <div className="flex items-center justify-between border-b border-border p-5">
                            <div className="font-display text-sm font-bold tracking-widest text-foreground">RECEIPT HISTORY</div>
                            <span className="hud-label">{range.label}{category !== "all" ? ` · ${category}` : ""}</span>
                        </div>
                        <div className="flex-1 overflow-y-auto p-5">
                            <RecentReceipts store={globalStore} start={range.start} end={range.end} category={category === "all" ? undefined : category}/>
                        </div>
                    </div>
                </div>

                <div className="pt-2 pb-6 text-center hud-label opacity-60">Bonfire · HUD build</div>
            </main>
        </div>
    )
}
