/* Compare page: two phones side by side, specs row by row, and a reasoned pick at the end. */
import { $, api, dayDate, escapeHtml, money, productName, safeUrl, showPage, state, variant } from "./core.js";
import { bestPriceSeries, inStock, openProductInCatalog, searchSuggestions } from "./catalog.js";
import { attachSuggestions } from "./combobox.js";
import { onLanguageChange, t } from "./i18n.js";

const SIDES = ["a", "b"];
const productById = id => state.products.find(product => product.id === Number(id));
const priceOf = product => Number(product.lowest_price);
const firstNumber = value => {
  const match = /(\d+(?:\.\d+)?)/.exec(String(value ?? ""));
  return match ? Number(match[1]) : null;
};
const storageGb = storage => {
  const match = /^(\d+)\s*(GB|TB)$/i.exec(storage || "");
  return match ? Number(match[1]) * (match[2].toUpperCase() === "TB" ? 1024 : 1) : null;
};
// "Apple A20 Pro" → 20.5, "Apple A18" → 18: newer generation first, Pro a half step up.
const chipScore = chip => {
  const match = /A(\d+)/.exec(chip || "");
  return match ? Number(match[1]) + (/\bPro\b/.test(chip) ? 0.5 : 0) : null;
};
// The main camera plus each "48 MP" / "48MP" lens in the extras.
const rearCameras = specs => specs.main_camera
  ? 1 + ((specs.extra_cameras || "").match(/\d\s*MP/gi) || []).length
  : null;
// Megapixels, not the aperture: "f/1.6, 48 MP" → 48.
const megapixels = camera => firstNumber(/(\d+(?:\.\d+)?)\s*MP/i.exec(camera || "")?.[1]);
const videoFps = video => firstNumber(/(\d+)\s*fps/i.exec(video || "")?.[1]);
const ipRating = rating => firstNumber(/IP(\d+)/i.exec(rating || "")?.[1]);

/*
 * One row of the spec table. score() gives a comparable number (null when unknown);
 * `better` says which way wins; `weight` is how much a win counts toward the pick.
 */
const ROWS = [
  { key: "price", show: d => money(d.product.lowest_price), score: d => (inStock(d.product) ? priceOf(d.product) : null), better: "lower" },
  { key: "chip", show: d => d.specs.chip, score: d => chipScore(d.specs.chip), better: "higher", weight: 3 },
  { key: "ram", show: d => d.specs.ram, score: d => firstNumber(d.specs.ram), better: "higher", weight: 2 },
  { key: "storage", show: d => d.product.storage, score: d => storageGb(d.product.storage), better: "higher", weight: 2 },
  { key: "display_size", show: d => d.specs.display_size?.replace(/inches?/i, "″").replace(/\s+″/, "″"), score: () => null },
  { key: "refresh_rate", show: d => d.specs.refresh_rate, score: d => firstNumber(d.specs.refresh_rate), better: "higher", weight: 2 },
  { key: "brightness", show: d => d.specs.brightness, score: d => firstNumber(d.specs.brightness), better: "higher", weight: 1 },
  { key: "rear_cameras", show: d => rearCameras(d.specs)?.toString(), score: d => rearCameras(d.specs), better: "higher", weight: 2 },
  { key: "main_camera", show: d => d.specs.main_camera, score: d => megapixels(d.specs.main_camera), better: "higher", weight: 1 },
  { key: "front_camera", show: d => d.specs.front_camera, score: d => megapixels(d.specs.front_camera), better: "higher", weight: 0.5 },
  { key: "video", show: d => d.specs.video, score: d => videoFps(d.specs.video), better: "higher", weight: 1 },
  { key: "wireless_charging", show: d => d.specs.wireless_charging, score: d => firstNumber(d.specs.wireless_charging), better: "higher", weight: 1 },
  { key: "weight", show: d => d.specs.weight, score: d => firstNumber(d.specs.weight), better: "lower", weight: 0.5 },
  { key: "water_resistance", show: d => d.specs.water_resistance, score: d => ipRating(d.specs.water_resistance), better: "higher", weight: 0.5 },
  { key: "release_year", show: d => d.specs.release_year, score: d => firstNumber(d.specs.release_year), better: "higher", weight: 1 },
];

// For each row: 0 or 1 when that side is strictly better, null on a tie or unknown.
function rowWinner(row, details) {
  const [a, b] = details.map(row.score);
  if (a == null || b == null || a === b) return null;
  return (row.better === "higher") === (a > b) ? 0 : 1;
}

// Side-by-side wins for one side, as reasons with weights.
function advantages(details, side) {
  return ROWS
    .filter(row => row.weight && rowWinner(row, details) === side)
    .map(row => ({
      weight: row.weight,
      text: t(`why.${row.key}`, { mine: row.show(details[side]), theirs: row.show(details[1 - side]) }),
    }));
}

const total = reasons => reasons.reduce((sum, reason) => sum + reason.weight, 0);
const fullName = product => `${productName(product)} ${variant(product)}`;

/* The pick: specs won by each phone weighed against how much more the pricier one costs. */
function recommend(details) {
  const [a, b] = details.map(detail => detail.product);
  if (!inStock(a) || !inStock(b)) {
    const available = inStock(a) ? 0 : inStock(b) ? 1 : null;
    if (available == null) return { side: null, headline: t("pick.neitherInStock"), reasons: [] };
    return { side: available, headline: t("pick.onlyInStock", { name: fullName(details[available].product) }), reasons: [] };
  }
  const wins = [advantages(details, 0), advantages(details, 1)];
  const gap = Math.abs(priceOf(a) - priceOf(b));
  if (gap < 1) {
    const side = total(wins[0]) === total(wins[1]) ? null : total(wins[0]) > total(wins[1]) ? 0 : 1;
    return side == null
      ? { side: null, headline: t("pick.equal"), reasons: [] }
      : { side, headline: t("pick.samePriceBetter", { name: fullName(details[side].product) }), reasons: wins[side] };
  }
  const cheaper = priceOf(a) < priceOf(b) ? 0 : 1;
  const pricier = 1 - cheaper;
  const share = gap / priceOf(details[cheaper].product);
  const extra = { amount: money(gap), percent: Math.round(share * 100) };
  if (!wins[pricier].length) {
    return {
      side: cheaper,
      headline: t("pick.cheaperNoLoss", { name: fullName(details[cheaper].product), ...extra }),
      reasons: wins[cheaper],
    };
  }
  // Worth paying more only for a clear step up that costs at most a quarter extra.
  if (total(wins[pricier]) >= total(wins[cheaper]) + 3 && share <= 0.25) {
    return {
      side: pricier,
      headline: t("pick.worthMore", { name: fullName(details[pricier].product), ...extra }),
      reasons: wins[pricier],
    };
  }
  return {
    side: cheaper,
    headline: t("pick.bestValue", { name: fullName(details[cheaper].product), ...extra }),
    reasons: wins[cheaper],
    tradeoff: t("pick.tradeoff", {
      name: fullName(details[pricier].product),
      gains: wins[pricier].map(reason => reason.text).join(", "),
    }),
  };
}

/* ---------- picking ---------- */

const pickerIds = () => SIDES.map(side => Number(new URLSearchParams(window.location.search).get(side)) || null)
  .map(id => (productById(id) ? id : null));

function saveSelection(ids) {
  const url = new URL(window.location.href);
  SIDES.forEach((side, index) => {
    if (ids[index] == null) url.searchParams.delete(side);
    else url.searchParams.set(side, ids[index]);
  });
  window.history.replaceState(window.history.state, "", url);
}

// The cheapest in-stock variant matching a model (and storage), falling back to any variant.
function defaultVariant(model, storage = null) {
  const candidates = state.products.filter(product => product.model === model && (!storage || product.storage === storage));
  return candidates.filter(inStock).sort((x, y) => priceOf(x) - priceOf(y))[0] || candidates[0] || null;
}

function chips(values, current, attribute) {
  return values.map(value => `
    <button class="chip${value === current ? " selected" : ""}" type="button" ${attribute}="${escapeHtml(value)}" aria-pressed="${value === current}">${escapeHtml(value)}</button>`).join("");
}

function renderPicker(side, productId) {
  const product = productById(productId);
  const input = $(`#compare-${side}-search`);
  const options = $(`#compare-${side}-options`);
  if (!product) {
    options.innerHTML = "";
    return;
  }
  if (document.activeElement !== input) input.value = productName(product);
  const variants = state.products.filter(item => item.model === product.model);
  const storages = [...new Set(variants.map(item => item.storage).filter(Boolean))]
    .sort((x, y) => (storageGb(x) ?? 0) - (storageGb(y) ?? 0));
  const colors = [...new Set(variants.filter(item => item.storage === product.storage).map(item => item.color).filter(Boolean))].sort();
  options.innerHTML = `
    ${storages.length > 1 ? `<div class="chip-row" role="group" aria-label="${escapeHtml(t("filters.storage"))}">${chips(storages, product.storage, "data-storage")}</div>` : ""}
    ${colors.length > 1 ? `<div class="chip-row" role="group" aria-label="${escapeHtml(t("compare.color"))}">${chips(colors, product.color, "data-color")}</div>` : ""}`;
}

function setSide(side, productId) {
  const ids = pickerIds();
  ids[SIDES.indexOf(side)] = productId;
  saveSelection(ids);
  renderPicker(side, productId);
  renderComparison(ids);
}

/* ---------- result ---------- */

async function productDetails(product) {
  const currency = product.currency || "GEL";
  const [listings, prices, extremes, specs] = await Promise.all([
    api(`/products/${product.id}/listings?limit=100`),
    api(`/products/${product.id}/prices?limit=100`),
    api(`/products/${product.id}/prices/extremes?currency=${encodeURIComponent(currency)}`),
    api(`/products/${product.id}/specs`),
  ]);
  return { product, listings: listings.items, series: bestPriceSeries(prices.items, currency), extremes, specs: specs.specs };
}

function summaryCard(detail) {
  const { product } = detail;
  const image = product.image_url
    ? `<img src="${escapeHtml(safeUrl(product.image_url))}" alt="" referrerpolicy="no-referrer">`
    : "<span>iPhone</span>";
  return `
    <article class="compare-card">
      <div class="history-product-image${product.image_url ? "" : " no-image"}">${image}</div>
      <div>
        <h3>${escapeHtml(productName(product))}</h3>
        <p class="muted">${escapeHtml(variant(product))}</p>
        <p class="card-price"><strong>${escapeHtml(money(product.lowest_price, product.currency || "GEL"))}</strong></p>
        <p class="card-meta">${escapeHtml(inStock(product) ? t("card.inStockAt", { count: product.available_listing_count }) : t("card.outOfStock"))}</p>
        ${product.lowest_installment_monthly != null ? `<p class="card-installment">${escapeHtml(t("card.installments", { amount: money(product.lowest_installment_monthly) }))}</p>` : ""}
      </div>
    </article>`;
}

function specTable(details) {
  const rows = ROWS.map(row => {
    const values = details.map(row.show);
    if (values.every(value => !value)) return "";
    const winner = rowWinner(row, details);
    const cell = (value, side) => `<td class="${winner === side ? "spec-win" : ""}">${escapeHtml(value || "—")}${winner === side ? ' <span class="spec-check" aria-hidden="true">✓</span>' : ""}</td>`;
    return `<tr><th scope="row">${escapeHtml(t(`spec.${row.key}`))}</th>${values.map(cell).join("")}</tr>`;
  }).join("");
  return `
    <div class="table-wrap"><table class="spec-table">
      <thead><tr><th></th>${details.map(detail => `<th>${escapeHtml(productName(detail.product))}<small>${escapeHtml(variant(detail.product))}</small></th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
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
    if (!listing) return '<td class="muted">—</td>';
    const price = escapeHtml(money(listing.current_price, listing.currency));
    const label = listing.is_available ? price : `${price} <small class="muted">${escapeHtml(t("stores.outOfStock"))}</small>`;
    return `<td><a href="${escapeHtml(safeUrl(listing.product_url))}" target="_blank" rel="noopener noreferrer">${label}</a></td>`;
  };
  const rows = [...stores]
    .sort(([x], [y]) => x.localeCompare(y))
    .map(([name, pair]) => `<tr><th scope="row">${escapeHtml(name)}</th>${cell(pair[0])}${cell(pair[1])}</tr>`)
    .join("");
  return `
    <div class="table-wrap"><table class="spec-table">
      <thead><tr><th>${escapeHtml(t("stores.store"))}</th>${details.map(detail => `<th>${escapeHtml(productName(detail.product))}<small>${escapeHtml(variant(detail.product))}</small></th>`).join("")}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

// Both best-price histories on one scale; stepped lines like the product chart.
function historyChart(details) {
  if (!details.some(detail => detail.series.length)) return `<p class="empty-inline">${escapeHtml(t("chart.noHistoryYet"))}</p>`;
  const W = 1000, H = 280, left = 80, right = 30, top = 20, bottom = 40;
  const points = details.flatMap(detail => detail.series);
  const times = points.map(point => new Date(point.recorded_at).getTime());
  const start = Math.min(...times);
  const end = Math.max(Date.now(), ...times);
  const prices = points.map(point => point.price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const pad = Math.max((max - min) * 0.1, 1);
  const x = time => left + (time - start) * (W - left - right) / (end - start || 1);
  const y = price => top + (max + pad - price) * (H - top - bottom) / (max - min + 2 * pad);
  const path = series => series.map((point, index) => {
    const px = x(new Date(point.recorded_at).getTime());
    return index === 0 ? `M ${px} ${y(point.price)}` : `H ${px} V ${y(point.price)}`;
  }).join(" ") + ` H ${x(end)}`;
  return `
    <ul class="compare-legend">${details.map((detail, index) => `<li class="compare-key-${SIDES[index]}">${escapeHtml(fullName(detail.product))}</li>`).join("")}</ul>
    <div class="chart-wrap"><svg class="compare-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeHtml(t("chart.label"))}">
      ${details.map((detail, index) => (detail.series.length ? `<path class="compare-line compare-line-${SIDES[index]}" d="${path(detail.series)}"/>` : "")).join("")}
      <text class="chart-label" x="${left - 10}" y="${y(max) + 4}" text-anchor="end">${escapeHtml(money(max))}</text>
      ${max !== min ? `<text class="chart-label" x="${left - 10}" y="${y(min) + 4}" text-anchor="end">${escapeHtml(money(min))}</text>` : ""}
      <text class="chart-label" x="${left}" y="${H - 10}">${escapeHtml(dayDate(start))}</text>
      <text class="chart-label" x="${W - right}" y="${H - 10}" text-anchor="end">${escapeHtml(t("chart.today"))}</text>
    </svg></div>`;
}

// The recommended phone, with links to it in All iPhones and at its cheapest store.
function pickedPhone(detail) {
  const { product } = detail;
  // Listings come in-stock first, cheapest first.
  const offer = detail.listings.find(listing => listing.is_available);
  return `
    <div class="compare-pick-phone">
      <p><strong>${escapeHtml(productName(product))}</strong> <span>${escapeHtml(variant(product))}</span></p>
      <div class="compare-pick-actions">
        <button class="primary-button" type="button" data-open-product="${product.id}">${escapeHtml(t("pick.viewInCatalog"))}</button>
        ${offer ? `<a class="small-button compare-pick-store" href="${escapeHtml(safeUrl(offer.product_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("pick.openAtStore", { store: offer.store_name, price: money(offer.current_price, offer.currency) }))} <svg aria-hidden="true"><use href="#i-external"/></svg></a>` : ""}
      </div>
    </div>`;
}

function pickBox(details) {
  const pick = recommend(details);
  return `
    <section class="compare-pick" aria-labelledby="comparePickTitle">
      <h2 id="comparePickTitle">${escapeHtml(t("pick.title"))}</h2>
      ${pick.side != null ? pickedPhone(details[pick.side]) : ""}
      <p class="compare-pick-headline">${escapeHtml(pick.headline)}</p>
      ${pick.reasons.length ? `<ul>${pick.reasons.map(reason => `<li>${escapeHtml(reason.text)}</li>`).join("")}</ul>` : ""}
      ${pick.tradeoff ? `<p class="muted">${escapeHtml(pick.tradeoff)}</p>` : ""}
      ${details.some(detail => !Object.keys(detail.specs).length) ? `<p class="muted">${escapeHtml(t("pick.missingSpecs"))}</p>` : ""}
    </section>`;
}

let renderToken = 0;

async function renderComparison(ids) {
  const result = $("#compareResult");
  const products = ids.map(productById);
  if (products.some(product => !product)) {
    result.innerHTML = `<p class="empty-inline">${escapeHtml(t("compare.prompt"))}</p>`;
    return;
  }
  if (products[0].id === products[1].id) {
    result.innerHTML = `<p class="empty-inline">${escapeHtml(t("compare.samePhone"))}</p>`;
    return;
  }
  const token = ++renderToken;
  result.innerHTML = `<p class="loading-state">${escapeHtml(t("loading"))}</p>`;
  try {
    const details = await Promise.all(products.map(productDetails));
    // A newer pick replaced this one while it loaded.
    if (token !== renderToken) return;
    result.innerHTML = `
      <div class="compare-cards">${details.map(summaryCard).join("")}</div>
      <h2>${escapeHtml(t("compare.specs"))}</h2>
      ${specTable(details)}
      <h2>${escapeHtml(t("stores.title"))}</h2>
      ${storeTable(details)}
      ${pickBox(details)}
      <h2>${escapeHtml(t("compare.history"))}</h2>
      ${historyChart(details)}`;
  } catch (error) {
    if (token === renderToken) result.innerHTML = `<p class="empty-inline">${escapeHtml(error.message)}</p>`;
  }
}

/* Draw the page from the a/b ids in the address bar; call once products are loaded. */
export function renderComparePage() {
  if (!state.products.length) return;
  const ids = pickerIds();
  SIDES.forEach((side, index) => renderPicker(side, ids[index]));
  renderComparison(ids);
}

/* "Compare" on a phone's detail: open the page with that phone first. */
export function openCompareWith(productId) {
  const url = new URL(window.location.href);
  url.searchParams.set("a", productId);
  url.searchParams.delete("b");
  window.history.replaceState(window.history.state, "", url);
  showPage("compare", true);
  renderComparePage();
  $("#compare-b-search").focus();
}

onLanguageChange(() => {
  if (state.currentPage === "compare") renderComparePage();
});

export function bindCompare() {
  SIDES.forEach(side => {
    // Model hints only (no storage), since storage and color are chosen with the chips.
    attachSuggestions($(`#compare-${side}-search`), {
      suggest: query => searchSuggestions(query).filter(item => state.products.some(product => productName(product) === item.value)),
      onPick: item => {
        $(`#compare-${side}-search`).value = item.value;
        const model = state.products.find(product => productName(product) === item.value)?.model;
        const product = model && defaultVariant(model);
        if (product) setSide(side, product.id);
      },
    });
    $(`#compare-${side}-options`).addEventListener("click", event => {
      const chip = event.target.closest(".chip");
      const current = productById(pickerIds()[SIDES.indexOf(side)]);
      if (!chip || !current) return;
      const next = chip.dataset.storage
        ? defaultVariant(current.model, chip.dataset.storage)
        : state.products.find(product => product.model === current.model
          && product.storage === current.storage && product.color === chip.dataset.color);
      if (next) setSide(side, next.id);
    });
  });
  $("#compareResult").addEventListener("click", event => {
    const button = event.target.closest("[data-open-product]");
    if (button) openProductInCatalog(button.dataset.openProduct);
  });
  $("#selectedCompareButton").addEventListener("click", () => {
    if (state.selectedId != null) openCompareWith(state.selectedId);
  });
}

// Selecting text on focus makes it quick to type a different model over the current one.
document.addEventListener("focusin", event => {
  if (event.target.matches?.(".compare-slot input")) event.target.select();
});
