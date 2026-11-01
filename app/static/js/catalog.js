/* Catalog search, offer cards, charts, and retailer comparison. */
import { $, $$, api, dateTime, escapeHtml, money, productName, relativeTime, safeUrl, state, variant, showToast } from "./core.js";

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
const byModel = (a, b) => naturalOrder.compare(baseModel(b), baseModel(a))
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
  fillSelect($("#modelFilter"), models, "All models");
  fillSelect($("#storageFilter"), storages, "Any storage");
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
  if (!state.products.length) grid.innerHTML = '<div class="loading-state">Loading prices…</div>';
  try {
    state.products = await fetchCatalog();
    renderOverview();
    populateFilters();
    applyFilters({ resetVisible: false });
    if (state.selectedId != null && state.products.some(item => item.id === state.selectedId)) {
      selectProduct(state.selectedId);
    } else if (state.visibleProducts.length) {
      const priced = state.visibleProducts.find(item => item.lowest_price != null) || state.visibleProducts[0];
      selectProduct(priced.id);
    }
  } catch (error) {
    $("#overviewStats").textContent = "Prices could not be loaded. Try again in a minute.";
    grid.innerHTML = `<div class="empty-state">Could not load prices.<br>${escapeHtml(error.message)}</div>`;
    $("#productCount").textContent = "Unavailable";
  }
}

const inStock = product => product.available_listing_count > 0 && product.lowest_price != null;
const storeCount = count => `${count} ${count === 1 ? "store" : "stores"}`;

// "−150 ₾ this week" when the best price fell by at least 1% over the last week.
function weekDrop(product) {
  if (!inStock(product) || product.price_week_ago == null) return "";
  const drop = Number(product.price_week_ago) - Number(product.lowest_price);
  if (drop < Number(product.price_week_ago) * 0.01) return "";
  return `<span class="card-change drop">−${escapeHtml(money(drop, product.currency || "GEL"))} this week</span>`;
}

// Price extremes span every store, so require the best price itself to have just fallen.
const isLowestEver = product => inStock(product)
  && product.price_week_ago != null
  && Number(product.price_week_ago) > Number(product.lowest_price)
  && Number(product.lowest_price) <= Number(product.lowest_price_ever);

function cardMeta(product) {
  if (!inStock(product)) return "Out of stock everywhere · last listed price";
  const saved = savings(product);
  const gap = saved >= 1 && product.available_listing_count > 1
    ? ` · <span class="savings">${escapeHtml(money(saved, product.currency || "GEL"))} cheaper than the priciest</span>`
    : "";
  return `In stock at ${storeCount(product.available_listing_count)}${gap}`;
}

// Today page: the cheapest in-stock variant of each model, newest model first.
export function renderOverview() {
  const list = $("#modelPrices");
  if (!state.products.length) return;
  const cheapest = new Map();
  for (const product of state.products.filter(inStock)) {
    const best = cheapest.get(product.model);
    if (!best || priceOf(product) < priceOf(best)) cheapest.set(product.model, product);
  }
  const listings = state.products.reduce((total, product) => total + Number(product.listing_count || 0), 0);
  const stats = [
    state.lastRefreshedAt ? `Updated <strong>${escapeHtml(relativeTime(state.lastRefreshedAt))}</strong>` : "",
    `<strong>${state.products.length.toLocaleString()}</strong> phones`,
    `<strong>${listings.toLocaleString()}</strong> store listings`,
    `<strong>${cheapest.size}</strong> models in stock`,
  ].filter(Boolean);
  $("#overviewStats").innerHTML = stats.join(" · ");
  const models = [...cheapest.values()].sort(byModel);
  list.innerHTML = models.length
    ? models.map(product => `
      <li class="model-price" data-model="${escapeHtml(product.model)}" data-product-id="${product.id}" tabindex="0">
        <span class="model-price-name">${escapeHtml(productName(product))}<small>${escapeHtml(variant(product))}</small></span>
        <span class="model-price-value">${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</span>
        <span class="model-price-meta">In stock at ${storeCount(product.available_listing_count)}${weekDrop(product) ? ` · ${weekDrop(product)}` : ""}</span>
      </li>`).join("")
    : '<li class="empty-state">No iPhone is in stock at any store we track right now.</li>';
}

export function renderProducts() {
  const products = state.visibleProducts;
  const total = products.length;
  $("#productCount").textContent = total === state.products.length
    ? `${total} ${total === 1 ? "product" : "products"}`
    : `${total} of ${state.products.length} products`;
  const grid = $("#productGrid");
  const showMore = $("#showMoreButton");
  const showLess = $("#showLessButton");
  if (!total) {
    grid.innerHTML = `<div class="empty-state">${state.products.length
      ? "No iPhones match these filters. Try another model or clear the filters."
      : "No iPhones are in the catalog yet. Products will appear after a retailer crawl succeeds."}</div>`;
    showMore.hidden = true;
    showLess.hidden = true;
    return;
  }
  const visibleProducts = products.slice(0, state.visibleCount);
  showMore.hidden = state.visibleCount >= total;
  showLess.hidden = state.visibleCount <= INITIAL_VISIBLE;
  showMore.textContent = `Show more · ${total - state.visibleCount} remaining`;
  grid.innerHTML = visibleProducts.map(product => {
    const tag = state.dealIds?.has(product.id)
      ? "Big gap between stores"
      : isLowestEver(product) ? "Lowest price we've recorded" : "";
    return `
    <article class="product-card${product.id === state.selectedId ? " selected" : ""}${state.dealIds?.has(product.id) ? " top-deal" : ""}${inStock(product) ? "" : " out-of-stock"}" data-product-id="${product.id}" tabindex="0">
      <div class="product-image${product.image_url ? "" : " no-image"}">
        ${product.image_url ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="${escapeHtml(productName(product))}" loading="lazy" referrerpolicy="no-referrer">` : ""}
        <span class="product-image-fallback">No photo</span>
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

export async function selectProduct(productId, { scroll = false } = {}) {
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
  $("#allTimeLow").textContent = "Loading…";
  $("#allTimeHigh").textContent = "Loading…";
  updateSelectedActions();
  $("#historySummary").innerHTML = `
    <div class="summary-item"><span>${inStock(product) ? "Cheapest now" : "Last listed"}</span><strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong></div>
    <div class="summary-item"><span>In stock</span><strong>${product.available_listing_count} of ${storeCount(product.listing_count)}</strong></div>`;
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
    if (scroll) {
      const details = $("#historySection");
      const top = details.getBoundingClientRect().top + window.scrollY - 88;
      window.scrollTo({ top: Math.max(top, 0), behavior: "instant" });
    }
  } catch (error) {
    showToast(error.message);
  }
}

function renderAllTimePrices(extremes) {
  const formatPrice = value => value == null
    ? "No recorded price"
    : money(value, extremes.currency);
  $("#allTimeLow").textContent = formatPrice(extremes.lowest_price);
  $("#allTimeHigh").textContent = formatPrice(extremes.highest_price);
}

// Records from one crawl (all stores) land within minutes; treat them as one moment.
const CRAWL_WINDOW_MS = 15 * 60 * 1000;
const shortDate = value => new Date(value).toLocaleDateString("en", { day: "numeric", month: "short" });

// Best in-stock price across stores over time, one point per change.
function bestPriceSeries(items, currency) {
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

// Indexes of the first and last points plus every peak and low in between.
function turningPoints(series) {
  return series.map((_, i) => i).filter(i => {
    if (i === 0 || i === series.length - 1) return true;
    const [before, here, after] = [series[i - 1].price, series[i].price, series[i + 1].price];
    return (here > before && here > after) || (here < before && here < after);
  });
}

export function renderChart(items, product) {
  const svg = $("#priceChart");
  const empty = $("#chartEmpty");
  const ordered = items?.length ? bestPriceSeries(items, product.currency || items[0].currency) : [];
  if (!ordered.length) {
    if (product.lowest_price != null) {
      empty.hidden = true;
      renderCurrentSnapshot(svg, product);
    } else {
      svg.innerHTML = "";
      empty.textContent = "Price history will appear after the first price is recorded.";
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
  const W = 1000, H = 320, left = singleRecord ? 132 : 28;
  const right = singleRecord ? 60 : 110, top = 42, bottom = 48;
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
  const tooltipX = lastX + 54;
  const tooltipY = Math.max(top, lastY - 100);
  const tooltipWidth = 320;
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
      <text class="chart-tooltip-date" x="${tooltipX + 16}" y="${tooltipY + 59}">Recorded ${lastDate.toLocaleDateString()}</text>
      <text class="chart-label chart-annotation" text-anchor="middle" x="${left + plotW / 2}" y="${lastY + 42}">The trend line starts after the next price change</text>` : `
      <circle class="chart-snapshot" cx="${lastX}" cy="${lastY}" r="5"><title>${escapeHtml(last.store_name)} — ${escapeHtml(money(last.price, currency))} — ${escapeHtml(dateTime(last.recorded_at))}</title></circle>
      <text class="chart-note" x="${lastX + 13}" y="${lastY + 4}">${escapeHtml(money(last.price, currency))}</text>`}
    <text class="chart-label" x="${left}" y="${H - 12}">${firstDate.toLocaleDateString()}</text>
    ${singleRecord ? "" : `<text class="chart-label" text-anchor="end" x="${W - right}" y="${H - 12}">${lastDate.toLocaleDateString()}</text>`}`;
}

function renderTrend(svg, series) {
  const W = 1000, H = 320, left = 40, right = 40, top = 56, bottom = 56;
  const plotW = W - left - right, plotH = H - top - bottom;
  const values = series.map(point => point.price);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max((max - min) * .08, 1);
  const start = new Date(series[0].recorded_at).getTime();
  const end = Math.max(Date.now(), new Date(series.at(-1).recorded_at).getTime());
  const x = time => left + (time - start) * plotW / (end - start || 1);
  const y = price => top + (max + padding - price) * plotH / (max - min + 2 * padding);
  const times = series.map(point => new Date(point.recorded_at).getTime());
  // Stepped: the best price holds until the next change, then to today.
  const path = series.map((point, i) => {
    const px = x(times[i]);
    const py = y(point.price);
    return i === 0 ? `M ${px} ${py}` : `H ${px} V ${py}`;
  }).join(" ") + ` H ${x(end)}`;
  const labels = turningPoints(series).map(i => {
    const point = series[i];
    const px = x(times[i]);
    const py = y(point.price);
    const isLow = i > 0 ? point.price < series[i - 1].price : point.price < series[i + 1].price;
    const anchor = px < left + 90 ? "start" : px > W - right - 90 ? "end" : "middle";
    const priceY = isLow ? py + 24 : py - 26;
    return `
      <circle class="chart-snapshot" cx="${px}" cy="${py}" r="5"><title>${escapeHtml(point.store_name)} — ${escapeHtml(money(point.price, point.currency))} — ${escapeHtml(dateTime(point.recorded_at))}</title></circle>
      <text class="chart-point-price" text-anchor="${anchor}" x="${px}" y="${priceY}">${escapeHtml(money(point.price, point.currency))}</text>
      <text class="chart-point-date" text-anchor="${anchor}" x="${px}" y="${priceY + 16}">${escapeHtml(shortDate(point.recorded_at))} · ${escapeHtml(point.store_name)}</text>`;
  }).join("");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    <path class="chart-line" d="${path}"/>
    ${labels}
    <text class="chart-label" x="${left}" y="${H - 8}">${escapeHtml(shortDate(start))}</text>
    <text class="chart-label" text-anchor="end" x="${W - right}" y="${H - 8}">Today</text>`;
}

function renderCurrentSnapshot(svg, product) {
  const W = 1000, H = 320, left = 28, right = 110, centerY = 220;
  const label = money(product.lowest_price, product.currency || "GEL");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `
    <line class="chart-line" x1="${left}" y1="${centerY}" x2="${W - right}" y2="${centerY}"/>
    <circle class="chart-snapshot" cx="${W - right}" cy="${centerY}" r="5"/>
    <text class="chart-note" x="${W - right + 14}" y="${centerY + 4}">${escapeHtml(label)}</text>
    <text class="chart-label" x="${left}" y="${centerY + 28}">${product.available_listing_count > 0 ? "Current listed price · history starts with the next change" : "Last listed price · currently unavailable"}</text>`;
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
    <tr class="${isBest ? "best-offer" : ""}">
      <td>
        <strong>${escapeHtml(item.store_name)}</strong>
        ${item.variant_name ? `<small class="listing-title">${escapeHtml(item.variant_name)}</small>` : ""}
      </td>
      <td class="listing-price">${escapeHtml(money(item.current_price, item.currency))}${isBest && items.length > 1 ? '<span class="best-tag">Cheapest</span>' : ""}</td>
      <td class="listing-diff">${difference ? `+${escapeHtml(money(difference, item.currency))}` : isBest ? "—" : ""}</td>
      <td><span class="status ${item.is_available ? "" : "unavailable"}">${item.is_available ? "In stock" : "Out of stock"}</span></td>
      <td title="${escapeHtml(dateTime(item.last_checked_at))}">${escapeHtml(relativeTime(item.last_checked_at))}</td>
      <td><a class="store-link" href="${escapeHtml(safeUrl(item.product_url))}" target="_blank" rel="noopener noreferrer" aria-label="Open listing at ${escapeHtml(item.store_name)}"><svg><use href="#i-external"/></svg></a></td>
    </tr>`;
  }).join("");
}

export function updateSelectedActions() {
  const tracked = state.tracked.some(item => item.product.id === state.selectedId);
  const button = $("#selectedTrackButton");
  button.textContent = tracked ? "Stop tracking" : "Track";
  button.classList.toggle("tracked", tracked);
  button.disabled = state.selectedId == null;
  const alertButton = $("#selectedAlertButton");
  alertButton.disabled = state.selectedId == null;
  alertButton.textContent = state.tracked.some(item => item.product.id === state.selectedId && item.active_alert)
    ? "Edit alert"
    : "Set alert";
}
