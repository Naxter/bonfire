"use client"

import { useState, useEffect, useRef } from "react"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { getReceiptsList, getReceiptDetails, updateItemCategory, getCategories } from "@/lib/api"
import { storeColor } from "@/lib/theme"
import { ChevronLeft, ChevronRight, Search, ShoppingCart, X } from "lucide-react"
import { toast } from "sonner"

// Fallback only — the live taxonomy is fetched from /categories so backend
// changes appear here without a frontend edit.
const CATEGORY_OPTIONS = [
  "Obst & Gemüse",
  "Molkereiprodukte & Eier",
  "Fleisch, Fisch & Veggie",
  "Backwaren",
  "Tiefkühlprodukte",
  "Nährmittel & Vorrat",
  "Gewürze, Saucen & Öle",
  "Konserven & Fertiggerichte",
  "Süßwaren & Snacks",
  "Getränke",
  "Haushalt & Non-Food",
  "Drogerie & Kosmetik",
  "Gutscheine & Rabatte",
  "Pfand",
  "Sonstiges",
  "Uncategorized"
]

interface RecentReceiptsProps {
  store?: string;
  start?: string;
  end?: string;
  category?: string;
}

export function RecentReceipts({ store = "all", start, end, category }: RecentReceiptsProps) {
  const [receipts, setReceipts] = useState<any[]>([])
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [isFetchingList, setIsFetchingList] = useState(false)
  const LIMIT = 10

  const [search, setSearch] = useState("")
  const [debouncedSearch, setDebouncedSearch] = useState("")

  const [isOpen, setIsOpen] = useState(false)
  const [activeDetails, setActiveDetails] = useState<any>(null)
  const [isLoadingDetails, setIsLoadingDetails] = useState(false)
  const [categoryOptions, setCategoryOptions] = useState<string[]>(CATEGORY_OPTIONS)

  // Ignore out-of-order list responses (filter change + page reset both fetch).
  const requestSeq = useRef(0)

  useEffect(() => {
    getCategories()
      .then((cats) => {
        if (Array.isArray(cats) && cats.length) {
          setCategoryOptions(cats.includes("Uncategorized") ? cats : [...cats, "Uncategorized"])
        }
      })
      .catch(() => {}) // keep the fallback list
  }, [])

  // Debounce the search box so we don't hit the API on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  // Any filter change resets to the first page.
  useEffect(() => {
    setCurrentPage(1)
  }, [store, start, end, category, debouncedSearch])

  useEffect(() => {
    loadPage(currentPage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, store, start, end, category, debouncedSearch])

  const loadPage = async (page: number) => {
    const seq = ++requestSeq.current
    setIsFetchingList(true)
    try {
      const data = await getReceiptsList(page, LIMIT, {
        store, search: debouncedSearch, start, end, category,
      })
      if (seq !== requestSeq.current) return // a newer request superseded this one
      setReceipts(data.items || [])
      setTotalCount(data.total || 0)
      setTotalPages(Math.ceil((data.total || 0) / LIMIT) || 1)
    } catch (error) {
      console.error("Failed to load receipts", error)
    } finally {
      if (seq === requestSeq.current) setIsFetchingList(false)
    }
  }

  const handleOpenReceipt = async (id: number) => {
    setIsOpen(true)
    setIsLoadingDetails(true)
    try {
      const details = await getReceiptDetails(id)
      setActiveDetails(details)
    } catch (error) {
      console.error("Failed to fetch details", error)
    } finally {
      setIsLoadingDetails(false)
    }
  }

  const handleCategoryChange = async (itemName: string, newCategory: string) => {
    try {
      const res = await updateItemCategory(itemName, newCategory)
      if (activeDetails) {
        const updatedDetails = await getReceiptDetails(activeDetails.receipt.id)
        setActiveDetails(updatedDetails)
      }
      toast.success(`Set “${itemName}” to ${newCategory}`, {
        description: res?.updated_items > 1 ? `Updated ${res.updated_items} matching items` : undefined,
      })
    } catch (error) {
      console.error("Failed to update category", error)
      toast.error(`Couldn't update “${itemName}”`)
    }
  }

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search receipts by store or item…"
          className="h-9 w-full rounded-md border border-primary/20 bg-secondary/40 pl-9 pr-9 text-sm text-foreground placeholder:text-muted-foreground outline-none transition-colors focus:border-primary/40"
        />
        {search && (
          <button
            type="button"
            onClick={() => setSearch("")}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="flex items-center justify-between px-0.5">
        <span className="hud-label">{totalCount} receipt{totalCount === 1 ? "" : "s"}</span>
        {debouncedSearch && <span className="hud-label text-primary truncate max-w-[60%]">“{debouncedSearch}”</span>}
      </div>

      <div className="space-y-2 min-h-[440px]">
        {isFetchingList && receipts.length === 0 ? (
          <div className="flex h-[400px] items-center justify-center">
            <div className="text-center text-sm text-muted-foreground">Loading page…</div>
          </div>
        ) : receipts.length === 0 ? (
          <div className="flex h-[400px] items-center justify-center">
            <div className="text-center text-sm text-muted-foreground">No receipts match your filters.</div>
          </div>
        ) : (
          receipts?.map((receipt) => {
            const key = (receipt.store_key || "").toLowerCase();
            const displayName = key === "rewe" ? "REWE" : key === "dm" ? "DM"
              : key ? key[0].toUpperCase() + key.slice(1) : "Other";
            const accent = storeColor(displayName);
            const initials = ((receipt.store_name || key || "?").replace(/[^A-Za-zÄÖÜäöü]/g, "").slice(0, 2) || "?").toUpperCase();
            return (
              <div
                key={receipt.id}
                className="group flex items-center p-3 rounded-xl border border-border bg-secondary/20 hover:bg-secondary/50 hover:border-primary/40 cursor-pointer transition-all duration-200"
                onClick={() => handleOpenReceipt(receipt.id)}
              >
                <Avatar className="h-10 w-10 border" style={{ borderColor: `${accent}55` }}>
                  <AvatarFallback className="font-bold" style={{ background: `${accent}1f`, color: accent }}>
                    {initials}
                  </AvatarFallback>
                </Avatar>
                <div className="ml-4 space-y-1 flex-1 min-w-0">
                  <p className="text-sm font-semibold leading-none truncate">{receipt.store_name}</p>
                  <p className="text-xs text-muted-foreground flex items-center gap-1">
                    {new Date(receipt.date).toLocaleDateString(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })}
                  </p>
                </div>
                <div className="ml-auto font-mono font-bold text-base neon-cyan">
                  -€{receipt.total_amount.toFixed(2)}
                </div>
              </div>
            )
          })
        )}
      </div>

      <div className="flex items-center justify-between pt-4 border-t border-border">
        <Button
          variant="outline"
          size="sm"
          className="border-primary/20 bg-secondary/40 hover:bg-secondary/70"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={currentPage === 1 || isFetchingList}
        >
          <ChevronLeft className="h-4 w-4 mr-1" /> Previous
        </Button>

        <span className="text-sm text-muted-foreground font-medium">
          Page <span className="neon-cyan font-bold">{currentPage}</span> of {totalPages}
        </span>

        <Button
          variant="outline"
          size="sm"
          className="border-primary/20 bg-secondary/40 hover:bg-secondary/70"
          onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
          disabled={currentPage === totalPages || isFetchingList}
        >
          Next <ChevronRight className="h-4 w-4 ml-1" />
        </Button>
      </div>

      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent className="max-w-3xl max-h-[90vh] flex flex-col border-primary/20">
          <DialogHeader className="border-b border-border pb-4">
            <DialogTitle className="text-2xl flex items-center gap-2 font-display tracking-wide">
              <ShoppingCart className="h-6 w-6 text-primary" />
              Receipt Details
            </DialogTitle>
            <DialogDescription className="text-base">
              {activeDetails?.receipt?.store_name} — <span className="font-medium">{activeDetails && new Date(activeDetails.receipt.date).toLocaleString()}</span>
            </DialogDescription>
          </DialogHeader>

          {isLoadingDetails ? (
            <div className="flex-1 flex items-center justify-center py-12">
              <div className="text-center text-muted-foreground text-sm">Loading items…</div>
            </div>
          ) : activeDetails ? (
            <>
              <ScrollArea className="h-[60vh] min-h-[300px] -mx-6 px-6">
                {/* Mobile: stacked cards so the category picker + price never run off-screen */}
                <div className="divide-y divide-border/60 sm:hidden">
                  {activeDetails.items.map((item: any) => (
                    <div key={item.id} className="flex items-start gap-3 py-3">
                      <span className="w-6 shrink-0 pt-2 text-xs font-medium text-muted-foreground">{item.quantity}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-sm font-medium leading-snug" title={item.name}>{item.name}</span>
                          <span className="shrink-0 font-mono text-sm font-medium">€{item.price_total.toFixed(2)}</span>
                        </div>
                        <div className="mt-1.5">
                          <Select
                            defaultValue={item.category || "Uncategorized"}
                            onValueChange={(val) => handleCategoryChange(item.name, val)}
                          >
                            <SelectTrigger className="h-8 w-full border-primary/20 bg-secondary/40 text-xs font-medium text-primary">
                              <SelectValue placeholder="Category" />
                            </SelectTrigger>
                            <SelectContent>
                              {categoryOptions.map((cat) => (
                                <SelectItem key={cat} value={cat} className="text-xs">{cat}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Desktop: full table */}
                <div className="hidden sm:block">
                <Table className="relative">
                  <TableHeader className="sticky top-0 bg-background/90 backdrop-blur z-10">
                    <TableRow className="hover:bg-transparent border-border">
                      <TableHead className="w-[60px] hud-label">Qty</TableHead>
                      <TableHead className="hud-label">Item</TableHead>
                      <TableHead className="w-[180px] hud-label">Category</TableHead>
                      <TableHead className="text-right hud-label">Price</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {activeDetails.items.map((item: any, index: number) => (
                      <TableRow key={item.id} className="border-border/60 hover:bg-secondary/40">
                        <TableCell className="font-medium text-muted-foreground">{item.quantity}</TableCell>
                        <TableCell className="font-medium">
                          <span className="line-clamp-1" title={item.name}>{item.name}</span>
                        </TableCell>
                        <TableCell>
                          <Select
                            defaultValue={item.category || "Uncategorized"}
                            onValueChange={(val) => handleCategoryChange(item.name, val)}
                          >
                            <SelectTrigger className="h-8 text-xs border-transparent bg-transparent hover:bg-secondary/60 hover:border-primary/30 focus:ring-0 focus:ring-offset-0 shadow-none font-medium text-primary">
                              <SelectValue placeholder="Category" />
                            </SelectTrigger>
                            <SelectContent>
                              {categoryOptions.map((cat) => (
                                <SelectItem key={cat} value={cat} className="text-xs">
                                  {cat}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                        <TableCell className="text-right font-mono font-medium">€{item.price_total.toFixed(2)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                </div>
              </ScrollArea>

              <div className="flex justify-between items-center pt-4 border-t border-border mt-auto">
                <span className="text-lg font-medium text-muted-foreground">Total Amount</span>
                <span className="text-3xl font-bold font-display neon-text">€{activeDetails.receipt.total_amount.toFixed(2)}</span>
              </div>
            </>
          ) : (
            <div className="py-12 text-center text-destructive text-sm font-medium">Failed to load data.</div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
