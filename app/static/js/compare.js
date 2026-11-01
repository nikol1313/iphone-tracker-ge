/* Compare page: two phones side by side, with prices per store and both price histories. */
import { $, api, dayDate, escapeHtml, money, productName, safeUrl, showPage, state, variant } from "./core.js";
import { bestPriceSeries, byModel, inStock } from "./catalog.js";
import { onLanguageChange, t } from "./i18n.js";

const SIDES = ["a", "b"];

const productById = id => state.products.find(product => product.id === Number(id));

function selectedIds() {
  const params = new URLSearchParams(window.location.search);
  return SIDES.map(side => (productById(params.get(side)) ? Number(params.get(side)) : null));
}

function saveSelection(ids) {
  const url = new URL(window.location.href);
  SIDES.forEach((side, index) => {
    if (ids[index] == null) url.searchParams.delete(side);
    else url.searchParams.set(side, ids[index]);
  });
  window.history.replaceState(window.history.state, "", url);
}

// One <select> per side: phones grouped by model, newest first, with today's best price.
function fillPickers(ids) {
  const groups = new Map();
  for (const product of [...state.products].sort(byModel)) {
    if (!groups.has(product.model)) groups.set(product.model, []);
    groups.get(product.model).push(product);
  }
  const options = [...groups].map(([model, products]) => `
    <optgroup label="${escapeHtml(model)}">${products.map(product => `
      <option value="${product.id}">${escapeHtml(productName(product))} · ${escapeHtml(variant(product))} — ${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</option>`).join("")}
    </optgroup>`).join("");
  SIDES.forEach((side, index) => {
    const select = $(`#compare-${side}`);
    select.innerHTML = `<option value="">${escapeHtml(t("compare.pick"))}</option>${options}`;
    select.value = ids[index] ?? "";
  });
}

async function productDetails(product) {
  const currency = product.currency || "GEL";
  const [listings, prices, extremes] = await Promise.all([
    api(`/products/${product.id}/listings?limit=100`),
    api(`/products/${product.id}/prices?limit=100`),
    api(`/products/${product.id}/prices/extremes?currency=${encodeURIComponent(currency)}`),
  ]);
  return { product, listings: listings.items, series: bestPriceSeries(prices.items, currency), extremes };
}

function summaryCard(detail) {
  const { product, extremes } = detail;
  const currency = product.currency || "GEL";
  const image = product.image_url
    ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="" referrerpolicy="no-referrer">`
    : `<span>iPhone</span>`;
  return `
    <article class="compare-card">
      <div class="history-product-image${product.image_url ? "" : " no-image"}">${image}</div>
      <h3>${escapeHtml(productName(product))}</h3>
      <p class="muted">${escapeHtml(variant(product))}</p>
      <p class="card-price"><strong>${escapeHtml(money(product.lowest_price, currency))}</strong></p>
      <p class="card-meta">${inStock(product) ? escapeHtml(t("card.inStockAt", { count: product.available_listing_count })) : escapeHtml(t("card.outOfStock"))}</p>
      ${product.lowest_installment_monthly != null ? `<p class="card-installment">${escapeHtml(t("card.installments", { amount: money(product.lowest_installment_monthly) }))}</p>` : ""}
      <dl class="compare-extremes">
        <div><dt>${escapeHtml(t("extremes.low"))}</dt><dd>${escapeHtml(money(extremes.lowest_price, currency))}</dd></div>
        <div><dt>${escapeHtml(t("extremes.high"))}</dt><dd>${escapeHtml(money(extremes.highest_price, currency))}</dd></div>
      </dl>
    </article>`;
}

function verdict([a, b]) {
  if (!inStock(a.product) || !inStock(b.product)) return t("compare.notBothInStock");
  const gap = Number(a.product.lowest_price) - Number(b.product.lowest_price);
  if (Math.abs(gap) < 1) return t("compare.samePrice");
  const [cheaper, pricier] = gap < 0 ? [a.product, b.product] : [b.product, a.product];
  return t("compare.cheaperBy", {
    cheaper: `${productName(cheaper)} ${variant(cheaper)}`,
    amount: money(Math.abs(gap)),
    pricier: `${productName(pricier)} ${variant(pricier)}`,
  });
}

// Each store that lists either phone, with both prices on one row.
function storeTable(details) {
  const stores = new Map();
  details.forEach((detail, index) => {
    for (const listing of detail.listings) {
      if (!stores.has(listing.store_name)) stores.set(listing.store_name, [null, null]);
      stores.get(listing.store_name)[index] = listing;
    }
  });
  const cell = listing => {
    if (!listing) return `<td class="muted">—</td>`;
    const price = escapeHtml(money(listing.current_price, listing.currency));
    const label = listing.is_available ? price : `${price} <small class="muted">${escapeHtml(t("stores.outOfStock"))}</small>`;
    return `<td><a href="${escapeHtml(safeUrl(listing.product_url))}" target="_blank" rel="noopener noreferrer">${label}</a></td>`;
  };
  const rows = [...stores]
    .sort(([nameA], [nameB]) => nameA.localeCompare(nameB))
    .map(([name, pair]) => `<tr><td><strong>${escapeHtml(name)}</strong></td>${cell(pair[0])}${cell(pair[1])}</tr>`)
    .join("");
  return `
    <div class="table-wrap"><table>
      <thead><tr><th>${escapeHtml(t("stores.store"))}</th>${details.map(detail => `<th>${escapeHtml(productName(detail.product))} · ${escapeHtml(variant(detail.product))}</th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

// Both best-price histories on one scale; stepped lines like the product chart.
function historyChart(details) {
  const lines = details.filter(detail => detail.series.length);
  if (!lines.length) return `<p class="empty-inline">${escapeHtml(t("chart.noHistoryYet"))}</p>`;
  const W = 1000, H = 300, left = 70, right = 30, top = 24, bottom = 40;
  const points = lines.flatMap(detail => detail.series);
  const times = points.map(point => new Date(point.recorded_at).getTime());
  const start = Math.min(...times);
  const end = Math.max(Date.now(), ...times);
  const prices = points.map(point => point.price);
  const pad = Math.max((Math.max(...prices) - Math.min(...prices)) * 0.1, 1);
  const low = Math.min(...prices) - pad, high = Math.max(...prices) + pad;
  const x = time => left + (time - start) * (W - left - right) / (end - start || 1);
  const y = price => top + (high - price) * (H - top - bottom) / (high - low || 1);
  const path = series => series.map((point, index) => {
    const px = x(new Date(point.recorded_at).getTime());
    return index === 0 ? `M ${px} ${y(point.price)}` : `H ${px} V ${y(point.price)}`;
  }).join(" ") + ` H ${x(end)}`;
  const body = details.map((detail, index) => detail.series.length
    ? `<path class="compare-line compare-line-${SIDES[index]}" d="${path(detail.series)}"/>`
    : "").join("");
  return `
    <ul class="compare-legend">${details.map((detail, index) => `<li class="compare-key-${SIDES[index]}">${escapeHtml(productName(detail.product))} · ${escapeHtml(variant(detail.product))}</li>`).join("")}</ul>
    <div class="chart-wrap"><svg class="compare-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t("chart.label"))}">
      ${body}
      <text class="chart-label" x="${left - 8}" y="${y(high - pad) + 4}" text-anchor="end">${escapeHtml(money(high - pad))}</text>
      <text class="chart-label" x="${left - 8}" y="${y(low + pad) + 4}" text-anchor="end">${escapeHtml(money(low + pad))}</text>
      <text class="chart-label" x="${left}" y="${H - 10}">${escapeHtml(dayDate(start))}</text>
      <text class="chart-label" x="${W - right}" y="${H - 10}" text-anchor="end">${escapeHtml(t("chart.today"))}</text>
    </svg></div>`;
}

let renderToken = 0;

async function renderComparison(ids) {
  const result = $("#compareResult");
  const products = ids.map(productById);
  if (products.some(product => !product)) {
    result.innerHTML = `<p class="empty-inline">${escapeHtml(t("compare.prompt"))}</p>`;
    return;
  }
  const token = ++renderToken;
  result.innerHTML = `<p class="loading-state">${escapeHtml(t("loading"))}</p>`;
  try {
    const details = await Promise.all(products.map(productDetails));
    // A newer pick replaced this one while it loaded.
    if (token !== renderToken) return;
    result.innerHTML = `
      <p class="compare-verdict">${escapeHtml(verdict(details))}</p>
      <div class="compare-cards">${details.map(summaryCard).join("")}</div>
      <h2>${escapeHtml(t("stores.title"))}</h2>
      ${storeTable(details)}
      <h2>${escapeHtml(t("compare.history"))}</h2>
      ${historyChart(details)}`;
  } catch (error) {
    if (token === renderToken) result.innerHTML = `<p class="empty-inline">${escapeHtml(error.message)}</p>`;
  }
}

/* Draw the page from the a/b ids in the address bar; call once products are loaded. */
export function renderComparePage() {
  if (!state.products.length) return;
  const ids = selectedIds();
  fillPickers(ids);
  renderComparison(ids);
}

/* "Compare" on a phone's detail: open the page with that phone on the left. */
export function openCompareWith(productId) {
  const url = new URL(window.location.href);
  url.searchParams.set("a", productId);
  url.searchParams.delete("b");
  window.history.replaceState(window.history.state, "", url);
  showPage("compare", true);
  renderComparePage();
}

onLanguageChange(() => {
  if (state.currentPage === "compare") renderComparePage();
});

export function bindCompare() {
  SIDES.forEach(side => {
    $(`#compare-${side}`).addEventListener("change", () => {
      const ids = SIDES.map(other => Number($(`#compare-${other}`).value) || null);
      saveSelection(ids);
      renderComparison(ids);
    });
  });
  $("#compareSwap").addEventListener("click", () => {
    const ids = selectedIds().reverse();
    saveSelection(ids);
    renderComparePage();
  });
  $("#selectedCompareButton").addEventListener("click", () => {
    if (state.selectedId != null) openCompareWith(state.selectedId);
  });
}
