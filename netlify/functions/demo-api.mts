/*
 * Read-only demo API for the static frontend on Netlify. The real FastAPI backend isn't
 * deployed here, so this serves a fixed, generated sample catalog in the same shapes.
 * Accounts, alerts, and refreshes are unavailable in the demo.
 */
import type { Config } from "@netlify/functions";

const STORES = ["Zoommer", "Alta", "iSpace", "Elit Electronics", "Megatechnica", "Extra.ge", "PCShop", "Metromart"];
const STORE_URLS: Record<string, string> = {
  Zoommer: "https://zoommer.ge",
  Alta: "https://alta.ge",
  iSpace: "https://ispace.ge",
  "Elit Electronics": "https://ee.ge",
  Megatechnica: "https://megatechnica.ge",
  "Extra.ge": "https://extra.ge",
  PCShop: "https://pcshop.ge",
  Metromart: "https://metromart.ge",
};

type Model = { model: string; base: number; colors: string[]; storages: string[]; specs: Record<string, string> };

const MODELS: Model[] = [
  {
    model: "iPhone 17 Pro Max", base: 4299, colors: ["Cosmic Orange", "Deep Blue", "Silver"], storages: ["256GB", "512GB", "1TB"],
    specs: { chip: "Apple A19 Pro", ram: "12 GB", display_size: "6.9 inches", refresh_rate: "120 Hz", brightness: "3000 nits", main_camera: "f/1.8, 48 MP", extra_cameras: "48 MP ultrawide, 48 MP telephoto", front_camera: "18 MP", video: "4K 120fps", wireless_charging: "25 W", weight: "231 g", water_resistance: "IP68", release_year: "2025" },
  },
  {
    model: "iPhone 17 Pro", base: 3899, colors: ["Cosmic Orange", "Deep Blue", "Silver"], storages: ["256GB", "512GB"],
    specs: { chip: "Apple A19 Pro", ram: "12 GB", display_size: "6.3 inches", refresh_rate: "120 Hz", brightness: "3000 nits", main_camera: "f/1.8, 48 MP", extra_cameras: "48 MP ultrawide, 48 MP telephoto", front_camera: "18 MP", video: "4K 120fps", wireless_charging: "25 W", weight: "206 g", water_resistance: "IP68", release_year: "2025" },
  },
  {
    model: "iPhone Air", base: 3499, colors: ["Sky Blue", "Space Black"], storages: ["256GB", "512GB"],
    specs: { chip: "Apple A19 Pro", ram: "12 GB", display_size: "6.5 inches", refresh_rate: "120 Hz", brightness: "3000 nits", main_camera: "f/1.6, 48 MP", front_camera: "18 MP", video: "4K 60fps", wireless_charging: "20 W", weight: "165 g", water_resistance: "IP68", release_year: "2025" },
  },
  {
    model: "iPhone 17", base: 2899, colors: ["Sage", "Lavender", "Black"], storages: ["256GB", "512GB"],
    specs: { chip: "Apple A19", ram: "8 GB", display_size: "6.3 inches", refresh_rate: "120 Hz", brightness: "3000 nits", main_camera: "f/1.6, 48 MP", extra_cameras: "48 MP ultrawide", front_camera: "18 MP", video: "4K 60fps", wireless_charging: "25 W", weight: "177 g", water_resistance: "IP68", release_year: "2025" },
  },
  {
    model: "iPhone 16 Pro", base: 3199, colors: ["Desert Titanium", "Black Titanium"], storages: ["128GB", "256GB"],
    specs: { chip: "Apple A18 Pro", ram: "8 GB", display_size: "6.3 inches", refresh_rate: "120 Hz", brightness: "2000 nits", main_camera: "f/1.78, 48 MP", extra_cameras: "48 MP ultrawide, 12 MP telephoto", front_camera: "12 MP", video: "4K 120fps", wireless_charging: "25 W", weight: "199 g", water_resistance: "IP68", release_year: "2024" },
  },
  {
    model: "iPhone 16", base: 2399, colors: ["Ultramarine", "Black", "Pink"], storages: ["128GB", "256GB"],
    specs: { chip: "Apple A18", ram: "8 GB", display_size: "6.1 inches", refresh_rate: "60 Hz", brightness: "2000 nits", main_camera: "f/1.6, 48 MP", extra_cameras: "12 MP ultrawide", front_camera: "12 MP", video: "4K 60fps", wireless_charging: "25 W", weight: "170 g", water_resistance: "IP68", release_year: "2024" },
  },
  {
    model: "iPhone 16e", base: 1799, colors: ["Black", "White"], storages: ["128GB", "256GB"],
    specs: { chip: "Apple A18", ram: "8 GB", display_size: "6.1 inches", refresh_rate: "60 Hz", brightness: "1200 nits", main_camera: "f/1.6, 48 MP", front_camera: "12 MP", video: "4K 60fps", wireless_charging: "7.5 W", weight: "167 g", water_resistance: "IP68", release_year: "2025" },
  },
  {
    model: "iPhone 15", base: 1999, colors: ["Black", "Blue"], storages: ["128GB", "256GB"],
    specs: { chip: "Apple A16 Bionic", ram: "6 GB", display_size: "6.1 inches", refresh_rate: "60 Hz", brightness: "2000 nits", main_camera: "f/1.6, 48 MP", extra_cameras: "12 MP ultrawide", front_camera: "12 MP", video: "4K 60fps", wireless_charging: "15 W", weight: "171 g", water_resistance: "IP68", release_year: "2023" },
  },
];

const STORAGE_EXTRA: Record<string, number> = { "128GB": 0, "256GB": 400, "512GB": 1100, "1TB": 1800 };
const HISTORY_DAYS = 30;
const DAY = 24 * 60 * 60 * 1000;

// Deterministic pseudo-random numbers so every request sees the same catalog.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

type Listing = {
  id: number; product_id: number; store_id: number; store_name: string; product_url: string;
  current_price: number; currency: string; is_available: boolean; last_checked_at: string;
  variant_name: string; installment_monthly: number | null; installment_months: number | null;
};
type PricePoint = {
  id: number; product_id: number; listing_id: number; store_id: number; store_name: string;
  price: number; currency: string; is_available: boolean; recorded_at: string;
};

// Anchor the dataset to the start of today so prices stay stable within a day.
const today = new Date();
today.setUTCHours(6, 0, 0, 0);
const now = today.getTime();

const products: any[] = [];
const listingsByProduct = new Map<number, Listing[]>();
const historyByProduct = new Map<number, PricePoint[]>();
const specsByProduct = new Map<number, { model: string; storage: string; specs: Record<string, string> }>();

let productId = 0;
let listingId = 0;
let pointId = 0;
for (const m of MODELS) {
  for (const storage of m.storages) {
    for (const color of m.colors) {
      const id = ++productId;
      const rand = rng(id * 7919);
      const base = m.base + STORAGE_EXTRA[storage];
      const storeCount = 3 + Math.floor(rand() * 5);
      const stores = [...STORES.keys()].sort(() => rand() - 0.5).slice(0, storeCount).sort((a, b) => a - b);
      const listings: Listing[] = [];
      const history: PricePoint[] = [];
      for (const storeIndex of stores) {
        const lid = ++listingId;
        const storeName = STORES[storeIndex];
        // Each store starts near list price, then drifts down with occasional bumps.
        let price = Math.round((base * (1 + rand() * 0.08)) / 10) * 10 - 1;
        const available = rand() > 0.12;
        for (let day = HISTORY_DAYS; day >= 0; day -= 3) {
          if (day < HISTORY_DAYS) {
            const r = rand();
            if (r < 0.35) price -= Math.round((base * rand() * 0.03) / 10) * 10;
            else if (r < 0.45) price += Math.round((base * rand() * 0.015) / 10) * 10;
          }
          history.push({
            id: ++pointId, product_id: id, listing_id: lid, store_id: storeIndex + 1, store_name: storeName,
            price, currency: "GEL", is_available: day === 0 ? available : true,
            recorded_at: new Date(now - day * DAY + storeIndex * 60_000).toISOString(),
          });
        }
        const hasInstallment = rand() > 0.5;
        listings.push({
          id: lid, product_id: id, store_id: storeIndex + 1, store_name: storeName,
          product_url: STORE_URLS[storeName], current_price: price, currency: "GEL", is_available: available,
          last_checked_at: new Date(now).toISOString(),
          variant_name: `Apple ${m.model} ${storage} - ${color}`,
          installment_monthly: hasInstallment ? Math.round(price / 24) : null,
          installment_months: hasInstallment ? 24 : null,
        });
      }
      const inStock = listings.filter(l => l.is_available);
      const offers = inStock.length ? inStock : listings;
      const prices = offers.map(l => l.current_price);
      const weekAgo = history.filter(p => p.recorded_at <= new Date(now - 7 * DAY).toISOString());
      const weekAgoLatest = new Map<number, number>();
      for (const p of weekAgo) weekAgoLatest.set(p.listing_id, p.price);
      const allPrices = history.map(p => p.price);
      const installments = inStock.map(l => l.installment_monthly).filter((v): v is number => v != null);
      products.push({
        id, brand: "Apple", model: m.model, storage, color, image_url: null,
        lowest_price: Math.min(...prices), currency: "GEL",
        listing_count: listings.length, available_listing_count: inStock.length,
        highest_price: inStock.length ? Math.max(...prices) : null,
        price_week_ago: weekAgoLatest.size ? Math.min(...weekAgoLatest.values()) : null,
        lowest_price_ever: Math.min(...allPrices), highest_price_ever: Math.max(...allPrices),
        lowest_installment_monthly: installments.length ? Math.min(...installments) : null,
      });
      listingsByProduct.set(id, listings);
      historyByProduct.set(id, history);
      specsByProduct.set(id, { model: m.model, storage, specs: m.specs });
    }
  }
}

const json = (data: unknown, status = 200) => Response.json(data, {
  status,
  headers: { "Cache-Control": "public, max-age=300" },
});
const page = (items: unknown[], url: URL) => {
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 50), 1), 100);
  const offset = Math.max(Number(url.searchParams.get("offset") || 0), 0);
  return json({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
};
const demoOnly = () => Response.json(
  { detail: "Accounts, alerts, and refreshes are unavailable in this demo." },
  { status: 503 },
);

export default async (req: Request) => {
  const url = new URL(req.url);
  const path = url.pathname.replace(/\/+$/, "");

  if (path === "/refresh") {
    if (req.method !== "GET") return demoOnly();
    return json({ last_refreshed_at: new Date(now).toISOString(), next_manual_refresh_at: null });
  }
  if (req.method !== "GET" || !path.startsWith("/products")) return demoOnly();

  if (path === "/products") {
    const filters = ["model", "storage", "color"] as const;
    const items = products.filter(p => filters.every(key => {
      const value = url.searchParams.get(key);
      return !value || p[key]?.toLowerCase() === value.toLowerCase();
    }));
    return page(items, url);
  }

  const match = /^\/products\/(\d+)(?:\/(prices\/extremes|prices|listings|specs))?$/.exec(path);
  const product = match && products.find(p => p.id === Number(match[1]));
  if (!product) return json({ detail: "Product not found" }, 404);

  switch (match[2]) {
    case undefined:
      return json(product);
    case "listings":
      return page(listingsByProduct.get(product.id)!, url);
    case "prices":
      // Newest first, like the real API.
      return page([...historyByProduct.get(product.id)!].reverse(), url);
    case "prices/extremes": {
      const currency = (url.searchParams.get("currency") || "GEL").toUpperCase();
      const prices = historyByProduct.get(product.id)!.filter(p => p.currency === currency).map(p => p.price);
      return json({
        currency,
        lowest_price: prices.length ? Math.min(...prices) : null,
        highest_price: prices.length ? Math.max(...prices) : null,
      });
    }
    case "specs": {
      const spec = specsByProduct.get(product.id)!;
      return json({
        product_id: product.id, model: spec.model, storage: spec.storage, specs: spec.specs,
        source_url: null, fetched_at: new Date(now).toISOString(),
      });
    }
  }
  return json({ detail: "Not found" }, 404);
};

export const config: Config = {
  path: [
    "/products", "/products/*", "/refresh", "/search", "/search/*", "/auth/*",
    "/tracked-products", "/tracked-products/*", "/alerts", "/alerts/*",
    "/notification-settings", "/notification-settings/*",
  ],
};
