/* Catalog search, offer cards, charts, and retailer comparison. */
import { $, $$, api, dateTime, escapeHtml, money, productName, safeUrl, state, variant, showToast } from "./core.js";

function setApiStatus(status) {
  const indicator = $("#apiStatus");
  const label = status === "connected" ? "API connected" : "API unavailable";
  indicator.dataset.state = status;
  indicator.setAttribute("aria-label", label);
  indicator.title = label;
}

export async function loadProducts(query = "", { focusFirst = false } = {}) {
  state.searchQuery = query;
  state.visibleCount = 8;
  const grid = $("#productGrid");
  grid.innerHTML = '<div class="loading-state">Loading products from the API…</div>';
  try {
    const endpoint = query ? `/search?q=${encodeURIComponent(query)}&limit=100` : "/products?limit=100";
    const page = await api(endpoint);
    setApiStatus("connected");
    state.products = Array.isArray(page.items) ? page.items : [];
    if (!query) {
      $("#overviewModelCount").textContent = Number(page.total || 0).toLocaleString();
      const listingCount = state.products.reduce(
        (total, product) => total + Number(product.listing_count || 0),
        0,
      );
      $("#overviewListingCount").textContent = listingCount.toLocaleString();
    }
    renderProducts(page.total);
    $("#clearSearch").hidden = !query;
    if (query && focusFirst && state.products.length) {
      await selectProduct(state.products[0].id, { scroll: true });
    } else if (!query && state.products.length) {
      const priced = state.products.find(item => item.lowest_price != null) || state.products[0];
      selectProduct(priced.id);
    }
  } catch (error) {
    setApiStatus("unavailable");
    $("#overviewModelCount").textContent = "—";
    $("#overviewListingCount").textContent = "—";
    grid.innerHTML = `<div class="empty-state">Could not load products.<br>${escapeHtml(error.message)}</div>`;
    $("#productCount").textContent = "Unavailable";
  }
}

export function renderProducts(total = state.products?.length || 0) {
  $("#productCount").textContent = `${total} ${total === 1 ? "product" : "products"}`;
  const grid = $("#productGrid");
  const showMore = $("#showMoreButton");
  const showLess = $("#showLessButton");
  if (!state.products?.length) {
    grid.innerHTML = `<div class="empty-state">${state.searchQuery
      ? "No iPhones match this search. Try another model or clear the search."
      : "No iPhones are in the catalog yet. Products will appear after a retailer crawl succeeds."}</div>`;
    showMore.hidden = true;
    showLess.hidden = true;
    return;
  }
  const visibleProducts = state.products.slice(0, state.visibleCount);
  showMore.hidden = state.visibleCount >= state.products.length;
  showLess.hidden = state.visibleCount <= 8;
  showMore.textContent = `Show more · ${state.products.length - state.visibleCount} remaining`;
  grid.innerHTML = visibleProducts.map(product => `
    <article class="product-card ${product.id === state.selectedId ? "selected" : ""}" data-product-id="${product.id}" tabindex="0">
      <div class="product-image${product.image_url ? "" : " no-image"}">
        ${product.image_url ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="${escapeHtml(productName(product))}" loading="lazy">` : ""}
        <span class="product-image-fallback">iPhone</span>
      </div>
      <div class="product-card-info">
        <h3>${escapeHtml(productName(product))}</h3>
        <div class="price-row"><div class="price">
          <strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong>
          <span class="price-status">${product.available_listing_count > 0
            ? `Available at ${product.available_listing_count} ${product.available_listing_count === 1 ? "store" : "stores"}`
            : "Currently unavailable"}</span>
        </div></div>
      </div>
    </article>`).join("");
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
    ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="">`
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
    <div class="summary-item"><span>${product.available_listing_count > 0 ? "Best available" : "Last listed"}</span><strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong></div>
    <div class="summary-item"><span>Listings</span><strong>${product.listing_count}</strong></div>`;
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

export function renderChart(items, product) {
  const svg = $("#priceChart");
  const empty = $("#chartEmpty");
  if (!items?.length) {
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
  const ordered = [...items].sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at));
  const values = ordered.map(item => Number(item.price));
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
      <text class="chart-label chart-annotation" text-anchor="middle" x="${left + plotW / 2}" y="${lastY + 42}">Awaiting next price update to build trend line…</text>` : `
      <circle class="chart-snapshot" cx="${lastX}" cy="${lastY}" r="5"><title>${escapeHtml(last.store_name)} — ${escapeHtml(money(last.price, currency))} — ${escapeHtml(dateTime(last.recorded_at))}</title></circle>
      <text class="chart-note" x="${lastX + 13}" y="${lastY + 4}">${escapeHtml(money(last.price, currency))}</text>`}
    <text class="chart-label" x="${left}" y="${H - 12}">${firstDate.toLocaleDateString()}</text>
    ${singleRecord ? "" : `<text class="chart-label" text-anchor="end" x="${W - right}" y="${H - 12}">${lastDate.toLocaleDateString()}</text>`}`;
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
  body.innerHTML = items.map(item => `
    <tr>
      <td><strong>${escapeHtml(item.store_name)}</strong></td>
      <td>${escapeHtml(money(item.current_price, item.currency))}</td>
      <td><span class="status ${item.is_available ? "" : "unavailable"}">${item.is_available ? "Available" : "Unavailable"}</span></td>
      <td>${escapeHtml(dateTime(item.last_checked_at))}</td>
      <td><a class="store-link" href="${escapeHtml(safeUrl(item.product_url))}" target="_blank" rel="noopener noreferrer" aria-label="Open listing at ${escapeHtml(item.store_name)}"><svg><use href="#i-external"/></svg></a></td>
    </tr>`).join("");
}

export function updateSelectedActions() {
  const tracked = state.tracked.some(item => item.product.id === state.selectedId);
  const button = $("#selectedTrackButton");
  button.textContent = tracked ? "Stop tracking" : "Track";
  button.classList.toggle("tracked", tracked);
  button.disabled = state.selectedId == null;
  $("#selectedAlertButton").disabled = state.selectedId == null;
}
