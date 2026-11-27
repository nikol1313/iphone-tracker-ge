/* Catalog search, offer cards, charts, and retailer comparison. */
import { $, $$, api, dateTime, dayDate, escapeHtml, money, productIdFromLocation, productName, relativeTime, safeUrl, setProductInLocation, shortDate, showPage, state, variant, showToast } from "./core.js";
import { onLanguageChange, t } from "./i18n.js";

const PAGE_LIMIT = 100;
const INITIAL_VISIBLE = 12;
// Highlight this many phones whose stores differ most in price.
const TOP_DEALS = 2;
const MIN_DEAL_SAVING = 50;
const naturalOrder = new Intl.Collator("en", { numeric: true, sensitivity: "base" });

// Storage like "512GB" or "1TB" in gigabytes, for ordering.
const storageSize = storage => {
  const match = /^(\d+)(GB|TB)$/i.exec(storage || "");
  if (!match) return 0;
  return Number(match[1]) * (match[2].toUpperCase() === "TB" ? 1024 : 1);
};
const savings = product => product.highest_price == null || product.lowest_price == null
  ? 0
  : Number(product.highest_price) - Number(product.lowest_price);
const isEsim = product => /\beSIM$/.test(product.model);
const baseModel = product => product.model.replace(/\s+eSIM$/, "");
// Newest generation first; within a model, the regular variant before its eSIM one.
export const byModel = (a, b) => naturalOrder.compare(baseModel(b), baseModel(a))
  || isEsim(a) - isEsim(b)
  || storageSize(a.storage) - storageSize(b.storage)
  || naturalOrder.compare(a.color || "", b.color || "");
const inStockFirst = (a, b) => (b.available_listing_count > 0) - (a.available_listing_count > 0);
const priceOf = product => product.lowest_price == null ? Infinity : Number(product.lowest_price);
const sorters = {
  model: (a, b) => inStockFirst(a, b) || byModel(a, b),
  "price-asc": (a, b) => priceOf(a) - priceOf(b) || byModel(a, b),
  "price-desc": (a, b) => (priceOf(b) === Infinity ? -1 : priceOf(b)) - (priceOf(a) === Infinity ? -1 : priceOf(a)) || byModel(a, b),
  savings: (a, b) => savings(b) - savings(a) || byModel(a, b),
  stores: (a, b) => b.available_listing_count - a.available_listing_count || byModel(a, b),
};

async function fetchCatalog() {
  const products = [];
  let total = 0;
  do {
    const page = await api(`/products?limit=${PAGE_LIMIT}&offset=${products.length}`);
    const items = Array.isArray(page.items) ? page.items : [];
    total = Number(page.total || 0);
    products.push(...items);
    if (!items.length) break;
  } while (products.length < total);
  return products;
}

function fillSelect(select, values, emptyLabel) {
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>`
    + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  select.value = values.includes(current) ? current : "";
}

function populateFilters() {
  const models = [...new Set(state.products.map(product => product.model))].sort((a, b) => naturalOrder.compare(b, a));
  const storages = [...new Set(state.products.map(product => product.storage).filter(Boolean))]
    .sort((a, b) => storageSize(a) - storageSize(b));
  fillSelect($("#modelFilter"), models, t("filters.allModels"));
  fillSelect($("#storageFilter"), storages, t("filters.anyStorage"));
}

const SUGGESTIONS_SHOWN = 8;
// Newest generation first; within one, the base model before Plus, Pro and Pro Max.
const generation = name => Number(/\d+/.exec(name)?.[0] ?? 99);
const bySuggestionOrder = (a, b) => generation(b.label) - generation(a.label) || naturalOrder.compare(a.label, b.label);

/*
 * Search hints: models whose name holds every typed term ("15" → iPhone 15, 15 Plus, 15 Pro…),
 * or a model + storage when a term names a storage size ("15 pro 256").
 */
export function searchSuggestions(query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const groups = new Map();
  for (const product of state.products) {
    const model = productName(product);
    const modelMatches = terms.every(term => model.toLowerCase().includes(term));
    const label = modelMatches ? model : `${model} ${product.storage || ""}`.trim();
    if (!modelMatches && !terms.every(term => label.toLowerCase().includes(term))) continue;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(product);
  }
  return [...groups].map(([label, products]) => {
    const prices = products.filter(inStock).map(priceOf);
    return {
      label,
      value: label,
      detail: prices.length ? t("search.from", { price: money(Math.min(...prices)) }) : t("search.outOfStock"),
    };
  }).sort(bySuggestionOrder).slice(0, SUGGESTIONS_SHOWN);
}

// Every whitespace-separated term must appear in the name, storage or color.
function matchesQuery(product, query) {
  const haystack = `${productName(product)} ${product.storage || ""} ${product.color || ""}`.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every(term => haystack.includes(term));
}

export function applyFilters({ resetVisible = true } = {}) {
  const model = $("#modelFilter").value;
  const storage = $("#storageFilter").value;
  const inStock = $("#inStockFilter").checked;
  const sortKey = sorters[$("#sortSelect").value] ? $("#sortSelect").value : "model";
  const filtered = state.products
    .filter(product => (!model || product.model === model)
      && (!storage || product.storage === storage)
      && (!inStock || product.available_listing_count > 0)
      && (!state.searchQuery || matchesQuery(product, state.searchQuery)))
    .sort(sorters[sortKey]);
  const deals = filtered
    .filter(product => product.available_listing_count >= 2 && savings(product) >= MIN_DEAL_SAVING)
    .sort((a, b) => savings(b) - savings(a) || byModel(a, b))
    .slice(0, TOP_DEALS);
  state.dealIds = new Set(deals.map(product => product.id));
  // The default view leads with the deals; explicit sorts keep their order.
  state.visibleProducts = sortKey === "model"
    ? [...deals, ...filtered.filter(product => !state.dealIds.has(product.id))]
    : filtered;
  if (resetVisible) state.visibleCount = INITIAL_VISIBLE;
  $("#clearFilters").hidden = !(model || storage || inStock || state.searchQuery);
  renderProducts();
}

export async function loadProducts() {
  const grid = $("#productGrid");
  if (!state.products.length) grid.innerHTML = `<div class="loading-state">${t("loadingPrices")}</div>`;
  try {
    state.products = await fetchCatalog();
    renderOverview();
    populateFilters();
    applyFilters({ resetVisible: false });
    if (state.selectedId != null && state.products.some(item => item.id === state.selectedId)) {
      selectProduct(state.selectedId);
    }
  } catch (error) {
    $("#overviewStats").textContent = t("intro.failed");
    grid.innerHTML = `<div class="empty-state">${t("products.loadFailed")}<br>${escapeHtml(error.message)}</div>`;
    $("#productCount").textContent = t("products.unavailable");
  }
}

export const inStock = product => product.available_listing_count > 0 && product.lowest_price != null;

// "9%" of the earlier price, or "<1%" for a move that rounds to nothing (pages.py _percent).
const percent = (change, base) => {
  const share = Math.round(Math.abs(change) * 100 / Number(base));
  return share ? `${share}%` : "<1%";
};

// "−150 ₾ (−5%) this week" when the best price fell by at least 1% over the last week.
function weekDrop(product) {
  const drop = weeklyDropAmount(product);
  if (!drop) return "";
  const amount = money(drop, product.currency || "GEL");
  return `<span class="card-change drop">${escapeHtml(t("card.weekDrop", { amount, percent: percent(drop, product.price_week_ago) }))}</span>`;
}

// Price extremes span every store, so require the best price itself to have just fallen.
const isLowestEver = product => inStock(product)
  && product.price_week_ago != null
  && Number(product.price_week_ago) > Number(product.lowest_price)
  && Number(product.lowest_price) <= Number(product.lowest_price_ever);

// One short line: "5 stores · save 350 ₾".
function cardMeta(product) {
  if (!inStock(product)) return t("card.outOfStock");
  const saved = savings(product);
  const gap = saved >= 1 && product.available_listing_count > 1
    ? ` · <span class="savings">${escapeHtml(t("card.save", { amount: money(saved, product.currency || "GEL") }))}</span>`
    : "";
  return `${t("card.stores", { count: product.available_listing_count })}${gap}`;
}

// How much the best in-stock price fell over the last week, or 0 below a 1% move.
function weeklyDropAmount(product) {
  if (!inStock(product) || product.price_week_ago == null) return 0;
  const drop = Number(product.price_week_ago) - Number(product.lowest_price);
  return drop >= Number(product.price_week_ago) * 0.01 ? drop : 0;
}

// Colors of one phone whose price moved alike share a row: [{ product, colors }], first one kept.
function groupColors(products, move) {
  const groups = new Map();
  for (const product of products) {
    const key = [product.model, product.storage, product.lowest_price, move(product)].join("|");
    if (!groups.has(key)) groups.set(key, { product, colors: [] });
    if (product.color) groups.get(key).colors.push(product.color);
  }
  return [...groups.values()];
}

// A color's name after a small swatch; shell.css knows the swatch colors by name.
// A small photo of the phone before its name; an empty frame keeps rows aligned when there is none.
const rowPhoto = product => `<span class="row-photo">${product.image_url ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}</span>`;

const colorLabel = color => `<span class="color-name"><span class="swatch" data-color="${escapeHtml(color)}" aria-hidden="true"></span>${escapeHtml(color)}</span>`;

// "256GB · ● Black ● Silver": storage, then each color.
const variantMeta = (storage, colors) => [storage ? escapeHtml(storage) : "", colors.map(colorLabel).join(" ")]
  .filter(Boolean).join(" · ") || escapeHtml(t("variant.unknown"));

const changePill = (change, base, currency) => `<span class="change-pill ${change < 0 ? "drop" : "rise"}">${escapeHtml(t(change < 0 ? "changes.down" : "changes.up", { amount: money(Math.abs(change), currency), percent: percent(change, base) }))}</span>`;

const CHANGE_BASE = { day: "price_day_ago", week: "price_week_ago" };

// How much the best in-stock price moved over the period (negative = cheaper):
// at least 1 ₾ since yesterday, or 1% over the week, else 0.
function priceChange(product, period) {
  const base = product[CHANGE_BASE[period]];
  if (!inStock(product) || base == null) return 0;
  const change = Number(product.lowest_price) - Number(base);
  const least = period === "week" ? Number(base) * 0.01 : 1;
  return Math.abs(change) >= least ? change : 0;
}

const CHANGES_SHOWN = 6;

// One storage-and-colors row; inside a model group it is named by its storage alone.
function changeRow({ product, colors }, period, { inGroup = false } = {}) {
  const change = priceChange(product, period);
  const base = product[CHANGE_BASE[period]];
  const currency = product.currency || "GEL";
  const name = inGroup ? product.storage || productName(product) : productName(product);
  const meta = inGroup ? colors.map(colorLabel).join(" ") : variantMeta(product.storage, colors);
  return `
    <li class="model-price" data-model="${escapeHtml(product.model)}" data-product-id="${product.id}" tabindex="0">
      ${inGroup ? "" : rowPhoto(product)}
      <span class="model-price-name">${escapeHtml(name)}</span>
      <span class="model-price-meta">${meta}</span>
      ${changePill(change, base, currency)}
      <span class="price-cell"><span class="model-price-value">${escapeHtml(money(product.lowest_price, currency))}</span><span class="price-was"><span class="sr-only">${escapeHtml(t("changes.was"))} </span>${escapeHtml(money(base, currency))}</span></span>
    </li>`;
}

// A model with several changed configs folds into one row: "5 configs · 512GB – 2TB · up to −7% · from 4,679 ₾".
function changeGroup(rows, period) {
  const { product } = rows[0];
  const products = rows.map(row => row.product);
  const share = p => Math.abs(priceChange(p, period)) / Number(p[CHANGE_BASE[period]]);
  const biggest = products.reduce((a, b) => share(b) > share(a) ? b : a);
  const change = priceChange(biggest, period);
  const sign = change < 0 ? "−" : "+";
  const cheapest = products.reduce((a, b) => priceOf(b) < priceOf(a) ? b : a);
  const storages = [...new Set(products.map(p => p.storage).filter(Boolean))].sort((a, b) => storageSize(a) - storageSize(b));
  const range = storages.length > 1 ? `${storages[0]} – ${storages.at(-1)}` : storages[0] || "";
  const meta = [t("changes.configs", { count: rows.length }), range].filter(Boolean).map(escapeHtml).join(" · ");
  return `
    <li class="change-group">
      <details>
        <summary class="change-summary">
          ${rowPhoto(product)}
          <span class="model-price-name">${escapeHtml(productName(product))}<svg aria-hidden="true"><use href="#i-chevron"/></svg></span>
          <span class="model-price-meta">${meta}</span>
          <span class="change-pill ${change < 0 ? "drop" : "rise"}">${escapeHtml(t("changes.upTo", { change: sign + percent(change, biggest[CHANGE_BASE[period]]) }))}</span>
          <span class="model-price-value">${escapeHtml(t("search.from", { price: money(cheapest.lowest_price, cheapest.currency || "GEL") }))}</span>
        </summary>
        <ul class="change-configs">${rows.map(row => changeRow(row, period, { inGroup: true })).join("")}</ul>
      </details>
    </li>`;
}

// Today page: what changed over the chosen period, drops first since that's what people come for.
function renderPriceChanges() {
  const changedIn = period => state.products.filter(product => priceChange(product, period) !== 0);
  state.changesPeriod ||= changedIn("day").length ? "day" : "week";
  const period = state.changesPeriod;
  const rows = groupColors(changedIn(period)
    .sort((a, b) => (priceChange(a, period) > 0) - (priceChange(b, period) > 0)
      || Math.abs(priceChange(b, period)) - Math.abs(priceChange(a, period))
      || byModel(a, b)), product => priceChange(product, period));
  // Same model, same direction: one entry, in the order of its biggest move.
  const entries = new Map();
  for (const row of rows) {
    const key = `${row.product.model}|${priceChange(row.product, period) < 0}`;
    if (!entries.has(key)) entries.set(key, []);
    entries.get(key).push(row);
  }
  $("#priceChangesSection").hidden = false;
  $("#priceChangesNote").textContent = t(period === "day" ? "changes.vsDay" : "changes.vsWeek");
  $$("#priceChangesSection [data-period]").forEach(button => {
    const on = button.dataset.period === period;
    button.classList.toggle("selected", on);
    button.setAttribute("aria-pressed", String(on));
  });
  const shown = [...entries.values()].slice(0, CHANGES_SHOWN);
  $("#priceChanges").innerHTML = shown.length
    ? shown.map(group => group.length > 1 ? changeGroup(group, period) : changeRow(group[0], period)).join("")
    : `<li class="empty-state">${t(period === "day" ? "changes.noneDay" : "changes.noneWeek")}</li>`;
}

// The headline model's 30-day best price, drawn like the phone page's chart at the svg's own width.
function renderIntroChart() {
  const svg = $("#introChart");
  if (!svg) return;
  let series;
  try {
    series = JSON.parse($("#introTrend").dataset.series || "[]").map(point => ({ ...point, price: Number(point.price), currency: "GEL" }));
  } catch {
    return;
  }
  if (series.length) renderTrend(svg, series);
}
let introChartWidth = 0;
if ($("#introChart")) {
  new ResizeObserver(() => {
    const { W } = chartSize($("#introChart"));
    if (W !== introChartWidth) {
      introChartWidth = W;
      renderIntroChart();
    }
  }).observe($("#introChart"));
}

// Once per page load the headline price counts down from the 30-day high to today's price,
// so the drop is the first thing a visitor sees. Skipped when the price didn't fall or motion is reduced.
let priceCounted = false;
function countDownPrice(span, target) {
  const high = Number($("#introTrend")?.dataset.high);
  if (priceCounted || !(high > target) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  priceCounted = true;
  const start = performance.now();
  const step = now => {
    const progress = Math.min(1, (now - start) / 900);
    const value = high - (high - target) * (1 - (1 - progress) ** 4);
    if (span.isConnected) span.textContent = money(value).replace(" ", " ");
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// How the headline price moved since the first day of its recorded series: green when it fell.
function renderIntroChange(price) {
  const box = $("#introChange");
  let first;
  try {
    [first] = JSON.parse($("#introTrend")?.dataset.series || "[]");
  } catch {
    first = null;
  }
  const delta = first ? price - Number(first.price) : 0;
  box.hidden = !delta;
  if (!delta) return;
  const days = Math.max(1, Math.round((Date.now() - new Date(first.recorded_at)) / 86400000));
  const percent = Math.abs(delta / Number(first.price) * 100).toFixed(1);
  const amount = `${delta < 0 ? "−" : "+"}${money(Math.abs(delta))} (${delta < 0 ? "−" : "+"}${percent}%)`;
  box.className = `intro-change ${delta < 0 ? "drop" : "rise"}`;
  box.textContent = t("intro.change", { amount, days });
}

// Today headline: the server picks the phone and counts; this writes them in the page language.
function renderIntro() {
  const title = $("#overviewTitle");
  const { model, price, store } = title.dataset;
  // The price is the answer, so it gets its own span; \u0000 marks its slot in the escaped sentence.
  // Non-breaking space keeps "2,799 ₾" together when the headline wraps.
  if (model) {
    const priceHtml = `<span class="intro-price">${escapeHtml(money(price).replace(" ", "\u00a0"))}</span>`;
    title.innerHTML = escapeHtml(t("intro.headline", { model, price: "\u0000", store })).replace("\u0000", priceHtml);
    countDownPrice(title.querySelector(".intro-price"), Number(price));
  }
  renderIntroChange(Number(price));
  // Written by the server in Georgian; the data attributes say which sentence and its numbers.
  $$("#introInsights li").forEach(item => {
    const { insight, store: shop, ...numbers } = item.dataset;
    const vars = Object.fromEntries(Object.entries(numbers).map(([key, value]) => [key, Number(value)]));
    item.textContent = t(`intro.${insight}`, { ...vars, store: shop });
  });
  renderIntroChart();
  const stats = $("#overviewStats");
  if (!stats.dataset.models) return;
  const parts = [
    t("intro.models", { count: Number(stats.dataset.models) }),
    t("intro.stores", { count: Number(stats.dataset.stores) }),
  ];
  if (stats.dataset.checked) parts.push(t("intro.checked", { time: relativeTime(stats.dataset.checked) }));
  stats.textContent = parts.join(" · ");
  const trend = $("#introTrend");
  if (trend.dataset.low) {
    trend.querySelector("figcaption").textContent = t("intro.trend", { low: money(trend.dataset.low), high: money(trend.dataset.high) });
  }
}

// The Today list starts folded to the newest few models.
const MODELS_FOLDED = 6;

// Today page: the cheapest in-stock variant of each model, newest model first.
export function renderOverview() {
  const list = $("#modelPrices");
  if (!state.products.length) return;
  renderPriceChanges();
  const cheapest = new Map();
  for (const product of state.products.filter(inStock)) {
    const best = cheapest.get(product.model);
    if (!best || priceOf(product) < priceOf(best)) cheapest.set(product.model, product);
  }
  const models = [...cheapest.values()].sort(byModel);
  const shown = state.modelsExpanded ? models : models.slice(0, MODELS_FOLDED);
  const toggle = $("#modelPricesToggle");
  toggle.hidden = models.length <= MODELS_FOLDED;
  toggle.setAttribute("aria-expanded", String(Boolean(state.modelsExpanded)));
  toggle.querySelector("span").textContent = state.modelsExpanded
    ? t("models.showFewer")
    : t("models.showAll", { count: models.length });
  list.innerHTML = models.length
    ? shown.map(product => `
      <li class="model-price" data-model="${escapeHtml(product.model)}" data-product-id="${product.id}" tabindex="0">
        ${rowPhoto(product)}
        <span class="model-price-name">${escapeHtml(productName(product))}</span>
        <span class="model-price-meta">${variantMeta(product.storage, product.color ? [product.color] : [])} · ${escapeHtml(t("card.stores", { count: product.available_listing_count }))}</span>
        ${weeklyDropAmount(product) ? changePill(-weeklyDropAmount(product), product.price_week_ago, product.currency || "GEL") : ""}
        <span class="model-price-value">${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</span>
      </li>`).join("")
    : `<li class="empty-state">${t("models.empty")}</li>`;
  list.removeAttribute("data-server-rendered");
}

export function renderProducts() {
  const products = state.visibleProducts;
  const total = products.length;
  $("#productCount").textContent = total === state.products.length
    ? t("products.count", { count: total })
    : t("products.countOf", { shown: total, total: state.products.length });
  const grid = $("#productGrid");
  const showMore = $("#showMoreButton");
  const showLess = $("#showLessButton");
  if (!total) {
    grid.innerHTML = `<div class="empty-state">${state.products.length
      ? t("products.noMatch")
      : t("products.empty")}</div>`;
    showMore.hidden = true;
    showLess.hidden = true;
    return;
  }
  const visibleProducts = products.slice(0, state.visibleCount);
  showMore.hidden = state.visibleCount >= total;
  showLess.hidden = state.visibleCount <= INITIAL_VISIBLE;
  showMore.textContent = t("showMore", { count: total - state.visibleCount });
  grid.innerHTML = visibleProducts.map(product => {
    const tag = state.dealIds?.has(product.id)
      ? t("card.bigGap")
      : isLowestEver(product) ? t("card.lowestEver") : "";
    return `
    <article class="product-card${product.id === state.selectedId ? " selected" : ""}${state.dealIds?.has(product.id) ? " top-deal" : ""}${inStock(product) ? "" : " out-of-stock"}" data-product-id="${product.id}" tabindex="0">
      <div class="product-image${product.image_url ? "" : " no-image"}">
        ${product.image_url ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="${escapeHtml(productName(product))}" loading="lazy" referrerpolicy="no-referrer">` : ""}
        <span class="product-image-fallback">${t("card.noPhoto")}</span>
      </div>
      ${tag ? `<span class="card-tag">${tag}</span>` : ""}
      <h3>${escapeHtml(productName(product))}</h3>
      <p class="product-variant">${escapeHtml(variant(product))}</p>
      <p class="card-price"><strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong>${weekDrop(product)}</p>
      <p class="card-meta">${cardMeta(product)}</p>
    </article>`;
  }).join("");
  $$(".product-image img", grid).forEach(image => image.addEventListener("error", () => {
    image.closest(".product-image")?.classList.add("no-image");
    image.remove();
  }, { once: true }));
}

/* Open one phone in All iPhones, with the grid behind it filtered to its model. */
export function openProductInCatalog(productId, { updateHistory = true } = {}) {
  const product = state.products.find(item => item.id === Number(productId));
  if (!product) return;
  $("#searchInput").value = "";
  state.searchQuery = "";
  $("#modelFilter").value = product.model;
  showPage("products", updateHistory);
  applyFilters();
  openProductDetail(product.id, { fromGrid: false });
}

/* All iPhones shows either the grid or one phone's page (history and stores); the address says which. */
const productsView = () => $('[data-page-view="products"]');
const showingDetail = () => productsView().hasAttribute("data-detail");

function setDetailMode(on) {
  productsView().toggleAttribute("data-detail", on);
}

// fromGrid: opened from the grid, so the back button and the browser's Back return to it.
export function openProductDetail(productId, { fromGrid = true } = {}) {
  const id = Number(productId);
  if (!state.products.some(item => item.id === id)) return;
  if (!showingDetail()) state.gridScroll = window.scrollY;
  setProductInLocation(id, { push: fromGrid });
  setDetailMode(true);
  window.scrollTo({ top: 0, behavior: "instant" });
  selectProduct(id);
}

export function closeProductDetail() {
  // Opened from the grid: step back to that history entry; syncProductsView redraws the grid.
  if (window.history.state?.detail) {
    window.history.back();
    return;
  }
  const url = new URL("/?page=products", window.location.origin);
  window.history.replaceState({ page: "products" }, "", url);
  syncProductsView();
}

// Match All iPhones to the address after Back/Forward or a nav click.
export function syncProductsView() {
  if (state.currentPage !== "products") return;
  const id = productIdFromLocation();
  if (id && state.products.some(item => item.id === id)) {
    setDetailMode(true);
    selectProduct(id);
    return;
  }
  const wasDetail = showingDetail();
  setDetailMode(false);
  if (wasDetail) window.scrollTo({ top: state.gridScroll || 0, behavior: "instant" });
}

export async function selectProduct(productId) {
  state.selectedId = Number(productId);
  const product = state.products.find(item => item.id === state.selectedId);
  if (!product) return;
  $$(".product-card").forEach(card => card.classList.toggle("selected", Number(card.dataset.productId) === state.selectedId));
  $("#historySection").hidden = false;
  $("#storesSection").hidden = false;
  const image = $("#historyProductImage");
  image.classList.toggle("no-image", !product.image_url);
  image.innerHTML = product.image_url
    ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="" referrerpolicy="no-referrer">`
    : "<span>iPhone</span>";
  image.querySelector("img")?.addEventListener("error", () => {
    image.classList.add("no-image");
    image.innerHTML = "<span>iPhone</span>";
  }, { once: true });
  $("#historyTitle").textContent = productName(product);
  $("#historyVariant").textContent = variant(product);
  $("#buyVerdict").innerHTML = buyVerdict(product);
  $("#allTimeLow").textContent = t("loading");
  $("#allTimeHigh").textContent = t("loading");
  updateSelectedActions();
  $("#historySummary").innerHTML = `
    <div class="summary-item"><span>${inStock(product) ? t("detail.cheapestNow") : t("detail.lastListed")}</span><strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong></div>
    <div class="summary-item"><span>${t("detail.inStock")}</span><strong>${t("detail.storesInStock", { available: product.available_listing_count, count: product.listing_count })}</strong></div>`;
  try {
    const currency = product.currency || "GEL";
    const [prices, listings, extremes] = await Promise.all([
      api(`/products/${product.id}/prices?limit=100`),
      api(`/products/${product.id}/listings?limit=100`),
      api(`/products/${product.id}/prices/extremes?currency=${encodeURIComponent(currency)}`),
    ]);
    renderChart(prices.items, product);
    renderListings(listings.items);
    renderAllTimePrices(extremes);
  } catch (error) {
    showToast(error.message);
  }
}

const DAY_MS = 24 * 60 * 60 * 1000;
// Matches the server's VERDICT_WINDOW and VERDICT_MIN_HISTORY.
const VERDICT_WINDOW_DAYS = 90;
const VERDICT_MIN_DAYS = 14;

/* "Buy now or wait?" for an in-stock phone, from the verdict the server works out. */
export function buyVerdict(product) {
  const since = product.price_tracked_since;
  if (!inStock(product) || !since) return "";
  const box = (kind, title, detail) => `
    <div class="verdict verdict-${kind}" role="status">
      <strong>${escapeHtml(title)}</strong>
      <p>${escapeHtml(detail)}</p>
    </div>`;
  if (!product.price_verdict) {
    return box("new", t("verdict.new"), t("verdict.newDetail", { date: dayDate(since), days: VERDICT_MIN_DAYS }));
  }
  const current = priceOf(product);
  const typical = Number(product.typical_price);
  const low = Number(product.recent_low_price);
  const period = Date.now() - new Date(since).getTime() < VERDICT_WINDOW_DAYS * DAY_MS
    ? t("verdict.since", { date: dayDate(since) })
    : t("verdict.lastDays", { days: VERDICT_WINDOW_DAYS });
  if (product.price_verdict === "good") {
    const detail = current <= low
      ? t("verdict.goodLow", { period })
      : current < typical
        ? t("verdict.goodBelow", { amount: money(typical - current), typical: money(typical) })
        : t("verdict.goodNearLow", { low: money(low), period });
    return box("good", t("verdict.good"), detail);
  }
  if (product.price_verdict === "wait") {
    return box("wait", t("verdict.wait"), t("verdict.waitDetail", { amount: money(current - typical), typical: money(typical), low: money(low), period }));
  }
  return box("normal", t("verdict.normal"), t("verdict.normalDetail", { typical: money(typical) }));
}

function renderAllTimePrices(extremes) {
  const formatPrice = value => value == null
    ? t("extremes.none")
    : money(value, extremes.currency);
  $("#allTimeLow").textContent = formatPrice(extremes.lowest_price);
  $("#allTimeHigh").textContent = formatPrice(extremes.highest_price);
}

// Records from one crawl (all stores) land within minutes; treat them as one moment.
const CRAWL_WINDOW_MS = 15 * 60 * 1000;

// Best in-stock price across stores over time, one point per change.
export function bestPriceSeries(items, currency) {
  const ordered = items
    .filter(item => item.currency === currency)
    .sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at));
  const latest = new Map();
  const series = [];
  for (let index = 0; index < ordered.length;) {
    const start = new Date(ordered[index].recorded_at);
    while (index < ordered.length && new Date(ordered[index].recorded_at) - start < CRAWL_WINDOW_MS) {
      const item = ordered[index++];
      if (item.is_available) latest.set(item.listing_id, item);
      else latest.delete(item.listing_id);
    }
    if (!latest.size) continue;
    const best = [...latest.values()].reduce((a, b) => (Number(b.price) < Number(a.price) ? b : a));
    if (series.length && Number(series.at(-1).price) === Number(best.price)) continue;
    series.push({ price: Number(best.price), currency, store_name: best.store_name, recorded_at: start.toISOString() });
  }
  return series;
}

// The chart is drawn in the SVG's own pixels, so lines and labels keep their size on a phone
// instead of a fixed 1000-wide drawing being shrunk to a third. Redrawn when its width changes.
let chartData = null;
let chartWidth = 0;
function chartSize(svg) {
  return { W: Math.round(svg.clientWidth) || 1000, H: Math.round(svg.clientHeight) || 320 };
}
new ResizeObserver(() => {
  const { W } = chartSize($("#priceChart"));
  if (chartData && W !== chartWidth) renderChart(...chartData);
}).observe($("#priceChart"));

export function renderChart(items, product) {
  const svg = $("#priceChart");
  chartData = [items, product];
  chartWidth = chartSize(svg).W;
  const empty = $("#chartEmpty");
  const ordered = items?.length ? bestPriceSeries(items, product.currency || items[0].currency) : [];
  if (!ordered.length) {
    if (product.lowest_price != null) {
      empty.hidden = true;
      renderCurrentSnapshot(svg, product);
    } else {
      svg.innerHTML = "";
      empty.textContent = t("chart.noHistoryYet");
      empty.hidden = false;
    }
    return;
  }
  empty.hidden = true;
  if (ordered.length > 1) {
    renderTrend(svg, ordered);
    return;
  }
  const values = ordered.map(item => item.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max((max - min) * .18, max * .025, 1);
  const low = min - padding;
  const high = max + padding;
  const singleRecord = ordered.length === 1;
  const { W, H } = chartSize(svg);
  const compact = W < 640;
  const left = singleRecord ? (compact ? 84 : 132) : 28;
  const right = singleRecord ? (compact ? 16 : 60) : 110, top = 42, bottom = 48;
  const plotW = W - left - right, plotH = H - top - bottom;
  const x = index => left + (singleRecord ? plotW * .2 : index * plotW / (ordered.length - 1));
  const y = value => top + (high - value) * plotH / (high - low || 1);
  const points = ordered.map((item, i) => `${x(i)},${y(Number(item.price))}`).join(" ");
  const currency = ordered[0].currency;
  const last = ordered.at(-1);
  const lastX = x(ordered.length - 1);
  const lastY = singleRecord ? top + plotH * .74 : y(Number(last.price));
  const firstDate = new Date(ordered[0].recorded_at);
  const lastDate = new Date(last.recorded_at);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  // Narrow screens: the price box sits above the point and stays inside the chart.
  const tooltipWidth = compact ? Math.min(240, W - 24) : 320;
  const tooltipX = compact ? Math.max(12, Math.min(lastX - 40, W - tooltipWidth - 12)) : lastX + 54;
  const tooltipY = Math.max(top, lastY - 100);
  const tooltipHeight = 76;
  svg.innerHTML = `
    ${singleRecord
      ? `<line class="chart-line chart-baseline" x1="${left}" y1="${lastY}" x2="${W - right}" y2="${lastY}"/>`
      : `<polyline class="chart-line" points="${points}"/>`}
    ${singleRecord ? `
      <text class="chart-note chart-axis-price" text-anchor="end" x="${left - 14}" y="${lastY + 6}">${escapeHtml(money(last.price, currency))}</text>
      <path class="chart-tooltip-link" d="M ${lastX + 8} ${lastY - 4} L ${tooltipX + 20} ${tooltipY + tooltipHeight}"/>
      <circle class="chart-snapshot chart-snapshot-large" cx="${lastX}" cy="${lastY}" r="13"><title>${escapeHtml(last.store_name)} — ${escapeHtml(money(last.price, currency))} — ${escapeHtml(dateTime(last.recorded_at))}</title></circle>
      <rect class="chart-tooltip" x="${tooltipX}" y="${tooltipY}" width="${tooltipWidth}" height="${tooltipHeight}" rx="12"/>
      <text class="chart-tooltip-price" x="${tooltipX + 16}" y="${tooltipY + 33}">${escapeHtml(money(last.price, currency))}</text>
      <text class="chart-tooltip-date" x="${tooltipX + 16}" y="${tooltipY + 59}">${escapeHtml(t("chart.recorded", { date: dayDate(lastDate) }))}</text>
      <text class="chart-label chart-annotation" text-anchor="middle" x="${compact ? W / 2 : left + plotW / 2}" y="${lastY + (compact ? 32 : 42)}">${trendNote(compact, W / 2)}</text>` : `
      <circle class="chart-snapshot" cx="${lastX}" cy="${lastY}" r="5"><title>${escapeHtml(last.store_name)} — ${escapeHtml(money(last.price, currency))} — ${escapeHtml(dateTime(last.recorded_at))}</title></circle>
      <text class="chart-note" x="${lastX + 13}" y="${lastY + 4}">${escapeHtml(money(last.price, currency))}</text>`}
    <text class="chart-label" x="${left}" y="${H - 12}">${escapeHtml(dayDate(firstDate))}</text>
    ${singleRecord ? "" : `<text class="chart-label" text-anchor="end" x="${W - right}" y="${H - 12}">${escapeHtml(dayDate(lastDate))}</text>`}`;
}

// SVG text doesn't wrap: on a phone the note goes on two lines, split between words.
function trendNote(compact, x) {
  const note = t("chart.trendStarts");
  if (!compact) return escapeHtml(note);
  const words = note.split(" ");
  const half = Math.ceil(words.length / 2);
  return `<tspan x="${x}">${escapeHtml(words.slice(0, half).join(" "))}</tspan><tspan x="${x}" dy="1.3em">${escapeHtml(words.slice(half).join(" "))}</tspan>`;
}

const plainNumber = value => new Intl.NumberFormat("en", { maximumFractionDigits: 0 }).format(Math.round(value));

// Round price steps for the gridlines: the smallest that leaves at most four lines.
function priceTicks(low, high) {
  const step = [10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000].find(s => (high - low) / s <= 3) || 10000;
  const ticks = [];
  for (let v = Math.ceil(low / step) * step; v <= high; v += step) ticks.push(v);
  return ticks;
}

// The best price over time as a stepped line with gridlines, dates, the period's high and today's
// price marked, and a crosshair box on hover or tap. Drawn in the SVG's own pixels.
function renderTrend(svg, series) {
  const { W, H } = chartSize(svg);
  const compact = W < 480;
  const left = 8, right = 56, top = 40, bottom = 30;
  const plotW = W - left - right, plotH = H - top - bottom;
  const values = series.map(point => point.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max((max - min) * .15, 10);
  const low = min - padding, high = max + padding;
  const start = new Date(series[0].recorded_at).getTime();
  const end = Math.max(Date.now(), new Date(series.at(-1).recorded_at).getTime());
  const x = time => left + (time - start) * plotW / (end - start || 1);
  const y = price => top + (high - price) * plotH / (high - low);
  const times = series.map(point => new Date(point.recorded_at).getTime());
  // Stepped: the best price holds until the next change, then to today.
  const line = series.map((point, i) => i === 0 ? `M ${x(times[i])} ${y(point.price)}` : `H ${x(times[i])} V ${y(point.price)}`).join(" ") + ` H ${x(end)}`;
  const floor = top + plotH;
  const grid = priceTicks(low, high).map(v => `
    <line class="chart-grid" x1="${left}" x2="${W - right}" y1="${y(v)}" y2="${y(v)}"/>
    <text class="chart-tick" x="${W - right + 8}" y="${y(v) + 4}">${plainNumber(v)}</text>`).join("");
  const dateCount = compact ? 3 : 5;
  const dates = Array.from({ length: dateCount }, (_, i) => start + (end - start) * i / (dateCount - 1)).map((time, i) => `
    <text class="chart-tick" text-anchor="${i === 0 ? "start" : i === dateCount - 1 ? "end" : "middle"}" x="${x(time)}" y="${H - 8}">${i === dateCount - 1 ? escapeHtml(t("chart.today")) : escapeHtml(shortDate(time))}</text>`).join("");
  const last = series.at(-1);
  const todayY = y(last.price);
  const peak = values.indexOf(max);
  // The high gets a label unless today is the high; today's label sits above the dot unless that's off the top.
  const highMark = max > last.price ? `
    <circle class="chart-high" cx="${x(times[peak])}" cy="${y(max)}" r="4"/>
    <text class="chart-flag chart-flag-high" text-anchor="${x(times[peak]) < left + 60 ? "start" : "middle"}" x="${x(times[peak])}" y="${y(max) - 12}">${escapeHtml(t("chart.high", { price: plainNumber(max) }))}</text>` : "";
  const todayLabelY = todayY - top > 28 ? todayY - 14 : todayY + 22;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    ${grid}
    <line class="chart-axis" x1="${left}" x2="${W - right}" y1="${floor}" y2="${floor}"/>
    <path class="chart-area" d="${line} V ${floor} H ${left} Z"/>
    <path class="chart-line chart-trend" d="${line}"/>
    ${highMark}
    <circle class="chart-today-halo" cx="${x(end)}" cy="${todayY}" r="10"/>
    <circle class="chart-today" cx="${x(end)}" cy="${todayY}" r="5"/>
    <text class="chart-flag chart-flag-today" text-anchor="end" x="${x(end) - 4}" y="${todayLabelY}">${escapeHtml(t("chart.todayPrice", { price: plainNumber(last.price) }))}</text>
    ${dates}
    <g class="chart-hover" hidden>
      <line class="chart-crosshair" y1="${top - 8}" y2="${floor}"/>
      <circle class="chart-hover-dot" r="5"/>
      <rect class="chart-hover-box" height="46" rx="8"/>
      <text class="chart-hover-date"></text>
      <text class="chart-hover-price"></text>
    </g>`;
  svg.trend = { series, times, x, y, left, right: W - right, start, end, W };
  if (svg.dataset.hover) return;
  // Bound once per svg; each redraw swaps svg.trend.
  svg.dataset.hover = "1";
  const show = event => {
    const { series: points, times: at, x: px, y: py, left: from, right: to, start: first, end: last, W: width } = svg.trend;
    const box = svg.getBoundingClientRect();
    const cx = Math.min(to, Math.max(from, (event.clientX - box.left) * width / box.width));
    const time = first + (cx - from) * (last - first) / (to - from || 1);
    let index = 0;
    while (index + 1 < at.length && at[index + 1] <= time) index++;
    const point = points[index];
    const hover = svg.querySelector(".chart-hover");
    const cy = py(point.price);
    // SVG elements have no .hidden property; the attribute is what the CSS reads.
    hover.removeAttribute("hidden");
    hover.querySelector(".chart-crosshair").setAttribute("x1", cx);
    hover.querySelector(".chart-crosshair").setAttribute("x2", cx);
    const dot = hover.querySelector(".chart-hover-dot");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", cy);
    const label = [shortDate(time), point.store_name].filter(Boolean).join(" · ");
    const boxWidth = Math.max(110, label.length * 7 + 24);
    const bx = Math.min(to - boxWidth, Math.max(from, cx - boxWidth / 2));
    const by = Math.max(0, cy - 64);
    const rect = hover.querySelector(".chart-hover-box");
    rect.setAttribute("x", bx);
    rect.setAttribute("y", by);
    rect.setAttribute("width", boxWidth);
    const date = hover.querySelector(".chart-hover-date");
    date.setAttribute("x", bx + 12);
    date.setAttribute("y", by + 18);
    date.textContent = label;
    const price = hover.querySelector(".chart-hover-price");
    price.setAttribute("x", bx + 12);
    price.setAttribute("y", by + 37);
    price.textContent = money(point.price, point.currency);
  };
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", () => {
    const hover = svg.querySelector(".chart-hover");
    hover?.setAttribute("hidden", "");
  });
}

function renderCurrentSnapshot(svg, product) {
  const { W, H } = chartSize(svg);
  const left = 28, right = 110, centerY = Math.round(H * .69);
  const label = money(product.lowest_price, product.currency || "GEL");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    <line class="chart-line" x1="${left}" y1="${centerY}" x2="${W - right}" y2="${centerY}"/>
    <circle class="chart-snapshot" cx="${W - right}" cy="${centerY}" r="5"/>
    <text class="chart-note" x="${W - right + 14}" y="${centerY + 4}">${escapeHtml(label)}</text>
    <text class="chart-label" x="${left}" y="${centerY + 28}">${product.available_listing_count > 0 ? t("chart.currentOnly") : t("chart.lastOnly")}</text>`;
}

function renderListings(items) {
  const body = $("#storesBody");
  $("#storesEmpty").hidden = Boolean(items?.length);
  if (!items?.length) {
    body.innerHTML = "";
    return;
  }
  // Listings arrive available-first, cheapest-first.
  const best = items.find(item => item.is_available);
  body.innerHTML = items.map(item => {
    const isBest = item === best;
    const difference = best && item.is_available && item.currency === best.currency
      ? Number(item.current_price) - Number(best.current_price)
      : null;
    return `
    <tr class="${isBest ? "best-offer" : ""}${item.is_available ? "" : " unavailable-offer"}">
      <td>
        <strong>${escapeHtml(item.store_name)}</strong>
        ${item.variant_name ? `<small class="listing-title">${escapeHtml(item.variant_name)}</small>` : ""}
      </td>
      <td class="listing-price">${escapeHtml(money(item.current_price, item.currency))}${isBest && items.length > 1 ? `<span class="best-tag">${t("stores.cheapest")}</span>` : ""}${item.installment_monthly != null ? `<small class="listing-installment">${escapeHtml(item.installment_months
          ? t("stores.installmentTerm", { amount: money(item.installment_monthly), months: item.installment_months })
          : t("stores.installment", { amount: money(item.installment_monthly) }))}</small>` : ""}</td>
      <td class="listing-diff">${difference ? `+${escapeHtml(money(difference, item.currency))}` : isBest ? "—" : ""}</td>
      <td><span class="status ${item.is_available ? "" : "unavailable"}">${item.is_available ? t("stores.inStock") : t("stores.outOfStock")}</span></td>
      <td title="${escapeHtml(dateTime(item.last_checked_at))}">${escapeHtml(relativeTime(item.last_checked_at))}</td>
      <td><a class="store-link" href="${escapeHtml(safeUrl(item.product_url))}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(t("stores.openAt", { store: item.store_name }))}"><svg><use href="#i-external"/></svg></a></td>
    </tr>`;
  }).join("");
}

// Redraw everything this module renders, keeping filters, scroll and the open phone.
renderIntro();
onLanguageChange(() => {
  renderIntro();
  if (!state.products.length) return;
  populateFilters();
  renderOverview();
  renderProducts();
  updateSelectedActions();
  if (state.selectedId != null) selectProduct(state.selectedId);
});

export function updateSelectedActions() {
  const tracked = state.tracked.some(item => item.product.id === state.selectedId);
  const button = $("#selectedTrackButton");
  button.textContent = tracked ? t("detail.stopTracking") : t("detail.track");
  button.classList.toggle("tracked", tracked);
  button.disabled = state.selectedId == null;
  const alertButton = $("#selectedAlertButton");
  alertButton.disabled = state.selectedId == null;
  alertButton.textContent = state.tracked.some(item => item.product.id === state.selectedId && item.active_alert)
    ? t("detail.editAlert")
    : t("detail.setAlert");
}
