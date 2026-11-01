/* Shared state and browser-level helpers. */
import { locale, onLanguageChange, t, translateServerMessage } from "./i18n.js";

export const state = {
  products: [],
  visibleProducts: [],
  searchQuery: "",
  tracked: [],
  selectedId: null,
  visibleCount: 12,
  currentPage: "overview",
  notificationSettings: null,
  resetToken: null,
  token: sessionStorage.getItem("priceMonitorToken"),
  email: sessionStorage.getItem("priceMonitorEmail"),
  authMode: "login",
};


export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const pages = new Set(["overview", "products", "compare", "alerts"]);
const pageTitleKeys = { overview: "title.overview", products: "title.products", compare: "title.compare", alerts: "title.alerts" };
// "3,199 ₾" the way Georgian stores write it; tetri only when there are any.
export const money = (value, currency = "GEL") => {
  if (value == null) return t("noPrice");
  const number = Number(value);
  const amount = new Intl.NumberFormat("en", {
    minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(number);
  return currency === "GEL" ? `${amount} ₾` : `${amount} ${currency}`;
};
// Browsers without Georgian locale data fall back to English in Intl; spell Georgian out ourselves.
const intlLacksGeorgian = Intl.RelativeTimeFormat.supportedLocalesOf(["ka"]).length === 0;
const georgianFallback = () => locale === "ka" && intlLacksGeorgian;
const GEORGIAN_MONTHS = ["იან", "თებ", "მარ", "აპრ", "მაი", "ივნ", "ივლ", "აგვ", "სექ", "ოქტ", "ნოე", "დეკ"];
const GEORGIAN_UNITS = { minute: ["წუთის წინ", "წუთში"], hour: ["საათის წინ", "საათში"], day: ["დღის წინ", "დღეში"] };
const relativeUnit = (amount, unit) => {
  if (!georgianFallback()) return new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(amount, unit);
  const [past, future] = GEORGIAN_UNITS[unit];
  return `${Math.abs(amount)} ${amount < 0 ? past : future}`;
};
export const relativeTime = value => {
  const minutes = Math.round((new Date(value) - Date.now()) / 60000);
  if (Math.abs(minutes) < 1) return georgianFallback() ? "ახლახან" : new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(0, "minute");
  if (Math.abs(minutes) < 60) return relativeUnit(minutes, "minute");
  if (Math.abs(minutes) < 48 * 60) return relativeUnit(Math.round(minutes / 60), "hour");
  return relativeUnit(Math.round(minutes / 1440), "day");
};
// "1 Nov" / "1 ნოე"
export const shortDate = value => {
  const date = new Date(value);
  return georgianFallback()
    ? `${date.getDate()} ${GEORGIAN_MONTHS[date.getMonth()]}`
    : date.toLocaleDateString(locale, { day: "numeric", month: "short" });
};
// "1 Nov 2026" / "1 ნოე 2026"
export const dayDate = value => {
  const date = new Date(value);
  return georgianFallback()
    ? `${shortDate(date)} ${date.getFullYear()}`
    : date.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
};
export const dateTime = value => {
  if (!value) return t("notAvailable");
  const date = new Date(value);
  if (!georgianFallback()) {
    return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
  }
  const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  return `${dayDate(date)}, ${time}`;
};
export const safeUrl = value => {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
};
export const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
})[char]);
export const productName = product => {
  const brand = String(product?.brand || "").trim();
  const model = String(product?.model || "").trim();
  if (/^iphone\b/i.test(model)) return model;
  const fullName = model.toLowerCase().startsWith(brand.toLowerCase()) ? model : [brand, model].filter(Boolean).join(" ");
  if (/\biphone\b/i.test(fullName)) return fullName;
  if (brand.toLowerCase() === "apple") return `iPhone ${model}`;
  return `iPhone ${fullName}`;
};
export const variant = product => product
  ? [product.storage, product.color].filter(Boolean).join(" · ") || t("variant.unknown")
  : t("variant.unknown");

export function pageFromLocation() {
  const requestedPage = new URLSearchParams(window.location.search).get("page");
  return pages.has(requestedPage) ? requestedPage : "overview";
}

function setPageTitle() {
  document.title = `${t(pageTitleKeys[state.currentPage])} — iPhone Tracker`;
}
onLanguageChange(setPageTitle);

export function showPage(page, updateHistory = false) {
  const nextPage = pages.has(page) ? page : "overview";
  state.currentPage = nextPage;
  $$("[data-page-view]").forEach(view => { view.hidden = view.dataset.pageView !== nextPage; });
  $$(".nav-link[data-page-link]").forEach(link => {
    const isCurrent = link.dataset.pageLink === nextPage;
    link.classList.toggle("active", isCurrent);
    if (isCurrent) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  setPageTitle();
  if (updateHistory) {
    const url = new URL(window.location.href);
    url.searchParams.set("page", nextPage);
    url.hash = "";
    window.history.pushState({ page: nextPage }, "", url);
  }
  window.scrollTo(0, 0);
}

export async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(item => item.msg).join(", ")
      : data.detail || t("error.unknown");
    const error = new Error(translateServerMessage(detail || t("error.unknown")));
    error.status = response.status;
    throw error;
  }
  return data;
}

export function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2800);
}
