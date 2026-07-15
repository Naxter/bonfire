import axios from 'axios';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const api = axios.create({
    // Configurable via NEXT_PUBLIC_API_URL; falls back to the local FastAPI port.
    baseURL: BASE_URL,
});

// --- Optional trusted-device token (BONFIRE_API_TOKEN on the backend) -------
export const TOKEN_STORAGE_KEY = 'bonfire.token';

export function getApiToken(): string {
    if (typeof window === 'undefined') return '';
    try { return window.localStorage.getItem(TOKEN_STORAGE_KEY) || ''; } catch { return ''; }
}

export function setApiToken(token: string) {
    try {
        if (token) window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
        else window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    } catch { /* private mode */ }
}

api.interceptors.request.use((config) => {
    const token = getApiToken();
    if (token) config.headers['X-Api-Token'] = token;
    return config;
});

/** Absolute API URL for <img>/<iframe>/download links (headers can't be set
 *  there, so the token rides along as a query parameter when configured). */
export function apiUrl(path: string): string {
    const token = getApiToken();
    const sep = path.includes('?') ? '&' : '?';
    return `${BASE_URL}${path}${token ? `${sep}token=${encodeURIComponent(token)}` : ''}`;
}

/** Best-effort human message out of an axios error. */
export function errorDetail(err: unknown): string | undefined {
    if (axios.isAxiosError(err)) {
        const data = err.response?.data as { detail?: string } | undefined;
        return data?.detail;
    }
    return undefined;
}

// Data-driven store list — the dropdown is built from this, so a new store
// added on the backend appears automatically with no frontend change.
export const getStores = async () => {
    const response = await api.get('/stores');
    return response.data as { key: string; display_name: string }[];
};

export interface DashboardStats {
    current_month_total: number;
    previous_month_total: number;
    diff_percent: number;
    receipt_count: number;
}

export const getDashboardStats = async (store: string = "all") => {
    const response = await api.get(`/stats/dashboard?store=${store}`);
    return response.data as DashboardStats;
};

// One row per month; every other key is a store display name mapped to € spent.
export interface MonthlyRow {
    month: string;
    [store: string]: number | string;
}

export const getMonthlyData = async (store: string = "all") => {
  const response = await api.get(`/stats/monthly?store=${store}`);
  return response.data as MonthlyRow[];
};

// A shared time range (ISO YYYY-MM-DD strings, end-exclusive) plus store.
export interface RangeFilter {
  store?: string;
  start?: string;
  end?: string;
}

export interface CategorySpend {
  name: string;
  value: number;
}

export const getCategoryData = async ({ store = "all", start, end }: RangeFilter = {}) => {
  const p = new URLSearchParams({ store });
  if (start) p.set("start", start);
  if (end) p.set("end", end);
  const response = await api.get(`/stats/category?${p.toString()}`);
  return response.data as CategorySpend[];
};

export interface ReceiptFilters extends RangeFilter {
  search?: string;
  category?: string;
  review?: string;
}

// Mirrors ReceiptPublic in backend/app/schemas.py; dates arrive as ISO strings.
export interface Receipt {
  id: number;
  store_name: string;
  store_key: string;
  store_address: string | null;
  date: string;
  total_amount: number;
  currency: string;
  pdf_filename: string;
  review_status: "ok" | "needs_review" | "verified";
  extraction_source: string;
  parse_warnings: string[];
  has_source: boolean;
  source_kind: "pdf" | "image" | null;
}

export interface ReceiptListRow extends Receipt {
  items_sum: number;
  total_mismatch: boolean;
}

export interface ReceiptsPage {
  items: ReceiptListRow[];
  total: number;
}

export const getReceiptsList = async (page: number, limit: number, f: ReceiptFilters = {}) => {
  const p = new URLSearchParams({ page: String(page), limit: String(limit), store: f.store || "all" });
  if (f.search) p.set("search", f.search);
  if (f.start) p.set("start", f.start);
  if (f.end) p.set("end", f.end);
  if (f.category && f.category !== "all") p.set("category", f.category);
  if (f.review && f.review !== "all") p.set("review", f.review);
  const response = await api.get(`/receipts?${p.toString()}`);
  return response.data as ReceiptsPage;
};

export const getCategories = async () => {
  const response = await api.get('/categories');
  return response.data as string[];
};

export interface ReceiptItem {
    id: number;
    receipt_id: number;
    product_id: number | null;
    name: string;
    clean_name: string;
    category: string;
    price_total: number;
    price_single: number | null;
    quantity: number;
    tax_rate: string | null;
    is_discounted: boolean;
    loyalty_qualified: boolean;
}

export interface ReceiptDetails {
    receipt: Receipt;
    items: ReceiptItem[];
    items_sum: number;
    total_mismatch: boolean;
    duplicates: Receipt[];
}

export const getReceiptDetails = async (id: number) => {
    const response = await api.get(`/receipts/${id}`);
    return response.data as ReceiptDetails;
};

export const getNeedsReviewCount = async () => {
    const response = await api.get('/receipts/needs-review-count');
    return response.data as { count: number };
};

export interface DuplicateGroup {
    store_key: string;
    date: string;
    total: number;
    receipts: Receipt[];
}

export const getDuplicateGroups = async () => {
    const response = await api.get('/receipts/duplicate-groups');
    return response.data as DuplicateGroup[];
};

// --- Receipt lifecycle -------------------------------------------------------
export interface ReceiptUpdatePayload {
    store_name?: string;
    store_key?: string;
    date?: string;
    total_amount?: number;
    currency?: string;
}

export const updateReceipt = async (id: number, data: ReceiptUpdatePayload) => {
    const response = await api.patch(`/receipts/${id}`, data);
    return response.data as { receipt: Receipt };
};

export const deleteReceipt = async (id: number) => {
    const response = await api.delete(`/receipts/${id}`);
    return response.data as { status: string };
};

export const verifyReceipt = async (id: number) => {
    const response = await api.post(`/receipts/${id}/verify`);
    return response.data as { receipt: Receipt };
};

export const reprocessReceipt = async (id: number) => {
    const response = await api.post(`/receipts/${id}/reprocess`);
    return response.data as { job_id: number };
};

export const receiptSourceUrl = (id: number) => apiUrl(`/receipts/${id}/source`);

export interface ItemUpdatePayload {
    name?: string;
    quantity?: number;
    price_total?: number;
    price_single?: number;
    category?: string;
    category_scope?: "all" | "item";
}

export const updateReceiptItem = async (receiptId: number, itemId: number, data: ItemUpdatePayload) => {
    const response = await api.patch(`/receipts/${receiptId}/items/${itemId}`, data);
    return response.data as { item: ReceiptItem; updated_items: number };
};

export const addReceiptItem = async (receiptId: number, data: { name: string; quantity?: number; price_total: number; category?: string }) => {
    const response = await api.post(`/receipts/${receiptId}/items`, data);
    return response.data as { item: ReceiptItem };
};

export const deleteReceiptItem = async (receiptId: number, itemId: number) => {
    const response = await api.delete(`/receipts/${receiptId}/items/${itemId}`);
    return response.data as { status: string };
};

export interface CategoryUpdateResult {
    status: string;
    updated_items: number;
    category: string;
    scope: string;
}

export const updateItemCategory = async (
    itemName: string, newCategory: string, scope: "all" | "item" = "all", itemId?: number,
) => {
    const response = await api.put('/categories/update', {
        item_name: itemName, new_category: newCategory, scope, item_id: itemId,
    });
    return response.data as CategoryUpdateResult;
};

export interface TopProduct {
    name: string;
    quantity: number;
    store: string;
}

export const getTopProducts = async ({ store = "all", start, end, category }: ReceiptFilters = {}) => {
    const p = new URLSearchParams({ store });
    if (start) p.set("start", start);
    if (end) p.set("end", end);
    if (category && category !== "all") p.set("category", category);
    const response = await api.get(`/stats/top-products?${p.toString()}`);
    return response.data as TopProduct[];
};

export interface VolatileItem {
    name: string;
    min_price: number;
    max_price: number;
    change_percent: number;
    times_bought: number;
    store: string;
}

export const getPriceVolatility = async (store: string = "all") => {
    const response = await api.get(`/stats/price-volatility?store=${store}`);
    return response.data as VolatileItem[];
};

export interface PricePoint {
    date: string;
    exact_date: string;
    iso_date: string;
    price: number;
}

export const getPriceHistory = async (itemName: string, store: string = "all") => {
  const response = await api.get(`/stats/price-history?item_name=${encodeURIComponent(itemName)}&store=${store}`);
  return response.data as PricePoint[];
};

export interface WalletShare {
    name: string;
    value: number;
}

export const getWalletShare = async (range: { start?: string; end?: string } = {}) => {
    const p = new URLSearchParams();
    if (range.start) p.set("start", range.start);
    if (range.end) p.set("end", range.end);
    const qs = p.toString();
    const response = await api.get(`/stats/wallet-share${qs ? `?${qs}` : ''}`);
    return response.data as WalletShare[];
};

export interface Health {
    status: "ok" | "degraded";
    db: boolean;
    llm_provider: string;
    llm_configured: boolean;
    mail_configured: boolean;
    auth_enabled: boolean;
    watcher?: { alive: boolean; last_seen: string | null };
    backup?: { last_at: string | null };
    imports?: { last_success_at: string | null; failed_24h: number };
    mail?: { configured: boolean; last_fetch_at: string | null; last_fetch_ok: boolean | null };
    receipts?: { count: number; needs_review: number };
    llm_probe?: { reachable: boolean; latency_ms?: number; error?: string; cached: boolean };
}

export const getHealth = async (probeLlm = false) => {
    const response = await api.get(`/health${probeLlm ? '?probe=llm' : ''}`);
    return response.data as Health;
};

// --- Import jobs ---------------------------------------------------------------
export interface ImportJob {
    id: number;
    kind: "upload" | "mail_fetch" | "watcher" | "reprocess";
    status: "queued" | "running" | "done" | "duplicate" | "needs_review" | "failed";
    filename: string | null;
    store_key: string | null;
    receipt_id: number | null;
    message: string | null;
    error: string | null;
    detail: Record<string, unknown>;
    created_at: string;
    finished_at: string | null;
}

export const getJobs = async (limit = 30) => {
    const response = await api.get(`/jobs?limit=${limit}`);
    return response.data as { jobs: ImportJob[]; active: number };
};

export const retryJob = async (jobId: number) => {
    const response = await api.post(`/jobs/${jobId}/retry`);
    return response.data as { job_id: number };
};

export const uploadReceiptFile = async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const response = await api.post('/ingest/upload', form);
    return response.data as { job_id: number };
};

// On-demand run of the REWE mail scraper — returns a tracked job.
export const fetchReweMails = async () => {
    const response = await api.post('/scrape/rewe');
    return response.data as { job_id: number };
};

// --- Daily-assistant features ---
export interface RestockItem {
    name: string; category: string; times_bought: number;
    avg_interval_days: number; last_purchased: string; due_in_days: number; overdue: boolean;
    suggested_qty: number;
}
// Without an argument the backend applies the horizon from the settings dialog.
export const getRestock = async (horizonDays?: number) => {
    const qs = horizonDays !== undefined ? `?horizon_days=${horizonDays}` : '';
    const response = await api.get(`/insights/restock${qs}`);
    return response.data as RestockItem[];
};

export type RestockActionKind = "dismiss" | "snooze" | "bought" | "add_to_list";

export const restockAction = async (name: string, action: RestockActionKind, days?: number) => {
    const response = await api.post('/insights/restock/actions', { name, action, days });
    return response.data as { status: string; added_to_list: boolean };
};

export interface HiddenRestock { name_key: string; action: string; until: string | null }

export const getHiddenRestock = async () => {
    const response = await api.get('/insights/restock/actions');
    return response.data as HiddenRestock[];
};

export const undoRestockAction = async (name: string) => {
    await api.delete(`/insights/restock/actions/${encodeURIComponent(name)}`);
};

// --- Shopping list ---------------------------------------------------------------
export interface ShoppingItem {
    id: number; name: string; quantity: number; unit: string | null;
    category: string | null; checked: boolean; source: string; created_at: string;
}

export const getShoppingList = async () => {
    const response = await api.get('/shopping-list');
    return response.data as ShoppingItem[];
};

export const addShoppingItem = async (name: string, quantity = 1) => {
    const response = await api.post('/shopping-list', { name, quantity });
    return response.data as ShoppingItem;
};

export const updateShoppingItem = async (id: number, data: Partial<Pick<ShoppingItem, "name" | "quantity" | "checked" | "unit">>) => {
    const response = await api.patch(`/shopping-list/${id}`, data);
    return response.data as ShoppingItem;
};

export const deleteShoppingItem = async (id: number) => {
    await api.delete(`/shopping-list/${id}`);
};

export const clearCheckedShopping = async () => {
    const response = await api.post('/shopping-list/clear-checked');
    return response.data as { removed: number };
};

// --- Pantry ---------------------------------------------------------------------
export interface PantryItem {
    id: number; name: string; quantity: number; unit: string | null;
    category: string | null; updated_at: string;
}

export const getPantry = async () => {
    const response = await api.get('/pantry');
    return response.data as PantryItem[];
};

export const addPantryItem = async (name: string, quantity = 1) => {
    const response = await api.post('/pantry', { name, quantity });
    return response.data as PantryItem;
};

export const updatePantryItem = async (id: number, data: Partial<Pick<PantryItem, "name" | "quantity" | "unit" | "category">>) => {
    const response = await api.patch(`/pantry/${id}`, data);
    return response.data as PantryItem;
};

export const deletePantryItem = async (id: number) => {
    await api.delete(`/pantry/${id}`);
};

export const pantryFromReceipt = async (receiptId: number) => {
    const response = await api.post(`/pantry/from-receipt/${receiptId}`);
    return response.data as { added: number; updated: number };
};

// App-level preferences (settings page). Infrastructure stays in .env.
export interface AppSettings {
    "meals.profile": string;
    "meals.count": number;
    "meals.context": "trip" | "days";
    "meals.days": number;
    "restock.horizon_days": number;
    "restock.min_purchases": number;
    "budget.history_months": number;
    "budget.anomaly_factor": number;
    "alerts.price_increase_pct": number;
}
export const getSettings = async () => {
    const response = await api.get('/settings');
    return response.data as AppSettings;
};
export const updateSettings = async (values: Partial<AppSettings>) => {
    const response = await api.put('/settings', values);
    return response.data as AppSettings;
};

export interface BudgetCategory {
    category: string; spent: number; projected: number; avg_month: number;
    delta_pct: number | null; anomaly: boolean;
    target: number | null; remaining: number | null;
    over_target: boolean; projected_over_target: boolean;
}
export interface BudgetChange { category: string; delta: number; spent: number; previous: number }
export interface Budget {
    month: string; days_elapsed: number; days_in_month: number;
    spent_so_far: number; projected_total: number;
    previous_month_to_date: number;
    target: number | null; remaining: number | null;
    over_target: boolean; projected_over_target: boolean;
    categories: BudgetCategory[]; anomalies: BudgetCategory[];
    alerts: BudgetCategory[]; changes: BudgetChange[];
}
export const getBudget = async () => {
    const response = await api.get('/insights/budget');
    return response.data as Budget;
};

export interface BudgetTargets { overall: number | null; categories: Record<string, number> }

export const getBudgetTargets = async () => {
    const response = await api.get('/budget/targets');
    return response.data as BudgetTargets;
};

export const putBudgetTargets = async (targets: { overall: number | null; categories: Record<string, number | null> }) => {
    const response = await api.put('/budget/targets', targets);
    return response.data as BudgetTargets;
};

// --- Products --------------------------------------------------------------------
export interface UnitPrice { value: number; unit: "kg" | "l" | "piece" }

export interface ProductRow {
    id: number; name_key: string; display_name: string; category: string;
    brand: string | null; size_value: number | null; size_unit: string | null;
    times_bought: number; total_qty: number; last_purchased: string | null;
    last_price: number | null; min_price: number | null; max_price: number | null;
    stores: { key: string; name: string }[];
    unit_price: UnitPrice | null;
}

export const getProducts = async (opts: { search?: string; category?: string; page?: number; limit?: number; sort?: string } = {}) => {
    const p = new URLSearchParams();
    if (opts.search) p.set("search", opts.search);
    if (opts.category && opts.category !== "all") p.set("category", opts.category);
    p.set("page", String(opts.page ?? 1));
    p.set("limit", String(opts.limit ?? 50));
    if (opts.sort) p.set("sort", opts.sort);
    const response = await api.get(`/products?${p.toString()}`);
    return response.data as { items: ProductRow[]; total: number };
};

export interface ProductDetail {
    product: { id: number; name_key: string; display_name: string; category: string; brand: string | null; size_value: number | null; size_unit: string | null };
    history: { date: string; price: number; store_key: string; store: string }[];
    stores: { store_key: string; store: string; latest_price: number; min_price: number; max_price: number; purchases: number; unit_price: UnitPrice | null }[];
    aliases: string[];
    receipt_names: string[];
}

export const getProductDetail = async (id: number) => {
    const response = await api.get(`/products/${id}`);
    return response.data as ProductDetail;
};

export const updateProduct = async (id: number, data: { display_name?: string; category?: string; brand?: string; size_value?: number | null; size_unit?: string | null }) => {
    const response = await api.patch(`/products/${id}`, data);
    return response.data as { product: ProductDetail["product"] };
};

export const mergeProducts = async (targetId: number, sourceIds: number[]) => {
    const response = await api.post('/products/merge', { target_id: targetId, source_ids: sourceIds });
    return response.data as { target_id: number; merged_keys: string[]; moved_items: number };
};

export interface PriceAlert {
    product_id: number; name: string; category: string; store: string; date: string;
    previous_price: number; latest_price: number; increase_pct: number;
    unit_price: UnitPrice | null;
}

export const getPriceAlerts = async () => {
    const response = await api.get('/insights/price-alerts');
    return response.data as PriceAlert[];
};

// --- Export ---------------------------------------------------------------------
export const exportUrls = () => ({
    csv: apiUrl('/export/items.csv'),
    json: apiUrl('/export/receipts.json'),
    db: apiUrl('/export/database'),
});

export const recategorize = async (scope: "missing" | "all" = "missing") => {
    const response = await api.post(`/categories/recategorize?scope=${scope}`);
    return response.data as { items_updated: number; names_processed: number };
};

export interface Meal {
    title: string; uses: string[]; missing?: string[];
    time_minutes?: number; note?: string; adaptation?: string | null;
}
export interface MealOptions {
    profile?: string; quick?: boolean; vegetarian?: boolean;
    context?: 'trip' | 'days'; days?: number; count?: number; avoid?: string[];
}
export interface MealsResponse {
    status: 'ok' | 'llm_error' | 'no_ingredients';
    ingredients: string[]; meals: Meal[];
    profile?: { key: string; name: string };
    context?: { mode: string; widened: boolean; label: string; pantry_items?: number };
}
export const getMeals = async (opts: MealOptions = {}) => {
    const p = new URLSearchParams();
    if (opts.profile) p.set('profile', opts.profile);
    if (opts.quick) p.set('quick', 'true');
    if (opts.vegetarian) p.set('vegetarian', 'true');
    if (opts.context) p.set('context', opts.context);
    if (opts.days) p.set('days', String(opts.days));
    if (opts.count) p.set('count', String(opts.count));
    for (const title of opts.avoid ?? []) p.append('avoid', title);
    const qs = p.toString();
    const response = await api.get(`/insights/meals${qs ? `?${qs}` : ''}`);
    return response.data as MealsResponse;
};

export interface MealProfile { id: number; key: string; name: string; prompt: string; is_builtin: boolean }
export const getMealProfiles = async () => {
    const response = await api.get('/meal-profiles');
    return response.data as MealProfile[];
};
export const createMealProfile = async (name: string, prompt: string) => {
    const response = await api.post('/meal-profiles', { name, prompt });
    return response.data as MealProfile;
};
export const updateMealProfile = async (id: number, name: string, prompt: string) => {
    const response = await api.put(`/meal-profiles/${id}`, { name, prompt });
    return response.data as MealProfile;
};
export const deleteMealProfile = async (id: number) => {
    await api.delete(`/meal-profiles/${id}`);
};

export interface AskResponse {
    question: string; rows?: Record<string, unknown>[]; answer?: string | null; error?: string;
}
export const ask = async (q: string) => {
    const response = await api.get(`/ask?q=${encodeURIComponent(q)}`);
    return response.data as AskResponse;
};

export default api;
