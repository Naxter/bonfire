import axios from 'axios';

const api = axios.create({
    // Configurable via NEXT_PUBLIC_API_URL; falls back to the local FastAPI port.
    baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
});

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
}

// Add the store parameter to your existing functions
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
}

// Mirrors ReceiptPublic in backend/app/main.py; dates arrive as ISO strings.
export interface Receipt {
  id: number;
  store_name: string;
  store_key: string;
  store_address: string | null;
  date: string;
  total_amount: number;
  currency: string;
  pdf_filename: string;
}

export interface ReceiptsPage {
  items: Receipt[];
  total: number;
}

export const getReceiptsList = async (page: number, limit: number, f: ReceiptFilters = {}) => {
  const p = new URLSearchParams({ page: String(page), limit: String(limit), store: f.store || "all" });
  if (f.search) p.set("search", f.search);
  if (f.start) p.set("start", f.start);
  if (f.end) p.set("end", f.end);
  if (f.category && f.category !== "all") p.set("category", f.category);
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
}

export const getReceiptDetails = async (id: number) => {
    const response = await api.get(`/receipts/${id}`);
    return response.data as ReceiptDetails;
};

export interface CategoryUpdateResult {
    status: string;
    updated_items: number;
    category: string;
}

export const updateItemCategory = async (itemName: string, newCategory: string) => {
    const response = await api.put(`/categories/update?item_name=${encodeURIComponent(itemName)}&new_category=${encodeURIComponent(newCategory)}`);
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

export const getWalletShare = async () => {
    const response = await api.get('/stats/wallet-share');
    return response.data as WalletShare[];
};

export interface Health {
    status: "ok" | "degraded";
    db: boolean;
    llm_provider: string;
    llm_configured: boolean;
}

export const getHealth = async () => {
    const response = await api.get('/health');
    return response.data as Health;
};

// --- Daily-assistant features ---
export interface RestockItem {
    name: string; category: string; times_bought: number;
    avg_interval_days: number; last_purchased: string; due_in_days: number; overdue: boolean;
}
export const getRestock = async (horizonDays = 3) => {
    const response = await api.get(`/insights/restock?horizon_days=${horizonDays}`);
    return response.data as RestockItem[];
};

export interface BudgetCategory {
    category: string; spent: number; projected: number; avg_month: number;
    delta_pct: number | null; anomaly: boolean;
}
export interface Budget {
    month: string; days_elapsed: number; days_in_month: number;
    spent_so_far: number; projected_total: number;
    categories: BudgetCategory[]; anomalies: BudgetCategory[];
}
export const getBudget = async () => {
    const response = await api.get('/insights/budget');
    return response.data as Budget;
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
    context?: { mode: string; widened: boolean; label: string };
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

export const uploadReceiptImage = async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const response = await api.post('/ingest/image', form);
    return response.data as { status: string; stored: boolean; store_name: string; total: number; items: number; date: string };
};

export default api;
