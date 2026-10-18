/* Shared state and browser-level helpers. */
export const state = {
  products: [],
  tracked: [],
  selectedId: null,
  visibleCount: 8,
  currentPage: "overview",
  notificationSettings: null,
  token: sessionStorage.getItem("priceMonitorToken"),
  email: sessionStorage.getItem("priceMonitorEmail"),
  authMode: "login",
};

localStorage.removeItem("telegramBotToken");
localStorage.removeItem("telegramChatId");

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const pages = new Set(["overview", "products", "alerts"]);
export const pageTitles = { overview: "Discover", products: "iPhones", alerts: "Watchlist" };
export const money = (value, currency = "GEL") => value == null
  ? "No price"
  : new Intl.NumberFormat("en", { style: "currency", currency }).format(Number(value));
export const dateTime = value => value
  ? new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "Not available";
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
  const fullName = model.toLowerCase().startsWith(brand.toLowerCase()) ? model : [brand, model].filter(Boolean).join(" ");
  if (/\biphone\b/i.test(fullName)) return fullName;
  if (brand.toLowerCase() === "apple") return `iPhone ${model}`;
  return `iPhone ${fullName}`;
};
export const variant = product => product
  ? [product.storage, product.color].filter(Boolean).join(" · ") || "Storage and color not specified"
  : "Storage and color not specified";

export function pageFromLocation() {
  const requestedPage = new URLSearchParams(window.location.search).get("page");
  return pages.has(requestedPage) ? requestedPage : "overview";
}

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
  document.title = `${pageTitles[nextPage]} — Price Monitor`;
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
      : data.detail || "Unknown error";
    const error = new Error(detail || `Request failed (${response.status})`);
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
