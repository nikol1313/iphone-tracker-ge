/* Compare page: two phones side by side, specs row by row, and a reasoned pick at the end. */
import { $, api, dayDate, escapeHtml, money, productName, safeUrl, showPage, state, variant } from "./core.js";
import { bestPriceSeries, buyVerdict, inStock, openProductInCatalog, searchSuggestions } from "./catalog.js";
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
  // Bigger isn't better for everyone: no tick in the table, and it only counts for uses that want it.
  { key: "display_size", show: d => d.specs.display_size?.replace(/inches?/i, "″").replace(/\s+″/, "″"), score: d => firstNumber(d.specs.display_size), better: "higher", plain: true },
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

/*
 * What the phone is for. Each use re-weighs the rows (a row it doesn't name keeps its own
 * weight) and caps how much more, as a share of the cheaper price, a clear step up is worth
 * while the cheaper phone has wins of its own.
 */
const USES = [
  { key: "everyday", weights: {}, maxExtra: 0.25 },
  {
    key: "gaming", maxExtra: 0.35,
    weights: { chip: 4, ram: 3, refresh_rate: 3, storage: 2, display_size: 1.5, rear_cameras: 0, main_camera: 0, front_camera: 0, video: 0, weight: 0, water_resistance: 0 },
  },
  {
    key: "creator", maxExtra: 0.35,
    weights: { video: 3, rear_cameras: 3, storage: 3, main_camera: 2, front_camera: 2, chip: 2, display_size: 1, ram: 1, refresh_rate: 1 },
  },
  { key: "longTerm", maxExtra: 0.3, weights: { release_year: 3, chip: 3, water_resistance: 1 } },
  // Saving money comes first: the cap holds even when the cheaper phone wins no spec.
  { key: "budget", weights: {}, maxExtra: 0.1, priceFirst: true },
];
const weightFor = (row, use) => use.weights[row.key] ?? row.weight ?? 0;

// For each row: 0 or 1 when that side is strictly better, null on a tie or unknown.
function rowWinner(row, details) {
  const [a, b] = details.map(row.score);
  if (a == null || b == null || a === b) return null;
  return (row.better === "higher") === (a > b) ? 0 : 1;
}

/*
 * Every spec where one phone beats the other, for both phones, whether or not it counts
 * for this use: key ones (the use boosts them) first, ones that matter less for it last.
 * Price isn't a spec here: the pick's headline already weighs it.
 */
function edges(details, side, use) {
  return ROWS
    .filter(row => row.key !== "price" && rowWinner(row, details) === side)
    .map(row => ({
      weight: weightFor(row, use),
      key: (use.weights[row.key] ?? 0) >= 3,
      text: t(`why.${row.key}`, { mine: row.show(details[side]), theirs: row.show(details[1 - side]) }),
    }))
    .sort((x, y) => y.weight - x.weight);
}

// The wins that count for this use: what the pick weighs.
const advantages = (details, side, use) => edges(details, side, use).filter(edge => edge.weight > 0);
const total = reasons => reasons.reduce((sum, reason) => sum + reason.weight, 0);
const fullName = product => `${productName(product)} ${variant(product)}`;

/* The pick for a use: specs won by each phone weighed against how much more the pricier one costs. */
function recommend(details, use) {
  const [a, b] = details.map(detail => detail.product);
  if (!inStock(a) || !inStock(b)) {
    const available = inStock(a) ? 0 : inStock(b) ? 1 : null;
    if (available == null) return { side: null, headline: t("pick.neitherInStock") };
    return { side: available, headline: t("pick.onlyInStock", { name: fullName(details[available].product) }) };
  }
  const wins = [advantages(details, 0, use), advantages(details, 1, use)];
  const useFor = t(`use.${use.key}.for`);
  const gap = Math.abs(priceOf(a) - priceOf(b));
  if (gap < 1) {
    const side = total(wins[0]) === total(wins[1]) ? null : total(wins[0]) > total(wins[1]) ? 0 : 1;
    return side == null
      ? { side: null, headline: t(SIDES.some((_, side) => edges(details, side, use).length) ? "pick.equalForUse" : "pick.equal", { use: useFor }) }
      : { side, headline: t("pick.samePriceBetter", { name: fullName(details[side].product), use: useFor }) };
  }
  const cheaper = priceOf(a) < priceOf(b) ? 0 : 1;
  const pricier = 1 - cheaper;
  const share = gap / priceOf(details[cheaper].product);
  const extra = { amount: money(gap), percent: Math.round(share * 100) };
  if (!wins[pricier].length) {
    return {
      side: cheaper,
      headline: t("pick.cheaperNoLoss", { name: fullName(details[cheaper].product), use: useFor, ...extra }),
    };
  }
  // The cheaper phone is no better at anything this use needs: price alone doesn't make it the pick.
  if (!wins[cheaper].length && total(wins[pricier]) >= 3 && !use.priceFirst) {
    return {
      side: pricier,
      headline: t("pick.betterAtAll", { name: fullName(details[pricier].product), use: useFor, ...extra }),
      tradeoff: t("pick.cheaperFallback", { name: fullName(details[cheaper].product), use: useFor, ...extra }),
    };
  }
  // Worth paying more only for a clear step up that costs no more extra than this use allows.
  if (total(wins[pricier]) >= total(wins[cheaper]) + 3 && share <= use.maxExtra) {
    return {
      side: pricier,
      headline: t("pick.worthMore", { name: fullName(details[pricier].product), use: useFor, ...extra }),
    };
  }
  return {
    side: cheaper,
    headline: t("pick.bestValue", { name: fullName(details[cheaper].product), use: useFor, ...extra }),
    tradeoff: t("pick.tradeoff", { name: fullName(details[pricier].product), use: useFor, ...extra }),
  };
}

/* ---------- picking ---------- */

const pickerIds = () => SIDES.map(side => Number(new URLSearchParams(window.location.search).get(side)) || null)
  .map(id => (productById(id) ? id : null));
const chosenUse = () => USES.find(use => use.key === new URLSearchParams(window.location.search).get("use")) || null;

function saveSelection(ids) {
  const url = new URL(window.location.href);
  SIDES.forEach((side, index) => {
    if (ids[index] == null) url.searchParams.delete(side);
    else url.searchParams.set(side, ids[index]);
  });
  window.history.replaceState(window.history.state, "", url);
}

function saveUse(key) {
  const url = new URL(window.location.href);
  url.searchParams.set("use", key);
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
        ${buyVerdict(product)}
      </div>
    </article>`;
}

function specTable(details) {
  const rows = ROWS.map(row => {
    const values = details.map(row.show);
    if (values.every(value => !value)) return "";
    const winner = row.plain ? null : rowWinner(row, details);
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
  // Buy now or wait: the same verdict as the phone's card, next to the decision. Skipped
  // while there's too little price history for one; the card says so already.
  const verdict = product.price_verdict ? buyVerdict(product) : "";
  return `
    <div class="compare-pick-phone">
      <p><strong>${escapeHtml(productName(product))}</strong> <span>${escapeHtml(variant(product))}</span></p>
      <div class="compare-pick-actions">
        <button class="primary-button" type="button" data-open-product="${product.id}">${escapeHtml(t("pick.viewInCatalog"))}</button>
        ${offer ? `<a class="small-button compare-pick-store" href="${escapeHtml(safeUrl(offer.product_url))}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("pick.openAtStore", { store: offer.store_name, price: money(offer.current_price, offer.currency) }))} <svg aria-hidden="true"><use href="#i-external"/></svg></a>` : ""}
      </div>
      ${verdict ? `<div class="compare-pick-timing"><p class="pick-label">${escapeHtml(t("pick.priceTiming"))}</p>${verdict}</div>` : ""}
    </div>`;
}

// "What's the phone for?": one button per use; the chosen one stays pressed.
function usePicker(chosen) {
  return `
    <fieldset class="use-picker">
      <legend>${escapeHtml(t("use.question"))}</legend>
      <div class="use-options">${USES.map(use => `
        <button class="use-option${use === chosen ? " selected" : ""}" type="button" data-use="${use.key}" aria-pressed="${use === chosen}">
          <strong>${escapeHtml(t(`use.${use.key}`))}</strong>
          <small>${escapeHtml(t(`use.${use.key}.hint`))}</small>
        </button>`).join("")}
      </div>
    </fieldset>`;
}

// How the spec wins for this use split between the two phones: one bar, a share each.
function scoreMeter(details, use) {
  const scores = SIDES.map((_, side) => total(advantages(details, side, use)));
  const sum = scores[0] + scores[1];
  if (!sum) return "";
  const firstShare = Math.round(scores[0] * 100 / sum);
  const shares = [firstShare, 100 - firstShare];
  const labels = details.map((detail, side) => `${fullName(detail.product)}: ${shares[side]}%`);
  return `
    <div class="score-meter">
      <p class="pick-label">${escapeHtml(t("pick.score", { use: t(`use.${use.key}.for`) }))}</p>
      <div class="score-bar" role="img" aria-label="${escapeHtml(labels.join(", "))}">${shares.map((share, side) => (share
        ? `<span class="score-${SIDES[side]}" style="--share: ${share}%"></span>` : "")).join("")}
      </div>
      <ul class="score-labels">${labels.map((label, side) => `<li class="score-key-${SIDES[side]}">${escapeHtml(label)}</li>`).join("")}</ul>
      <p class="muted score-note">${escapeHtml(t("pick.scoreNote"))}</p>
    </div>`;
}

// Where each phone is better than the other, side by side.
function edgeLists(details, use) {
  const useFor = t(`use.${use.key}.for`);
  const item = (edge, index) => `
    <li class="${edge.weight ? "" : "edge-minor"}" style="--i: ${index}">${escapeHtml(edge.text)}${edge.key
      ? ` <span class="edge-tag">${escapeHtml(t("pick.keyFor", { use: useFor }))}</span>`
      : edge.weight ? "" : ` <span class="edge-note">(${escapeHtml(t("pick.minorFor", { use: useFor }))})</span>`}</li>`;
  return `
    <div class="compare-edges">${details.map((detail, side) => {
      const list = edges(details, side, use);
      return `
      <div class="compare-edge">
        <h3>${escapeHtml(t("pick.betterAt", { name: fullName(detail.product) }))}</h3>
        ${list.length ? `<ul>${list.map(item).join("")}</ul>` : `<p class="muted">${escapeHtml(t("pick.noEdge"))}</p>`}
      </div>`;
    }).join("")}
    </div>`;
}

// The pick waits until the visitor says what the phone is for.
function pickBox(details) {
  const use = chosenUse();
  const pick = use && recommend(details, use);
  const result = pick ? `
    <div>
      ${pick.side != null ? pickedPhone(details[pick.side]) : ""}
      <p class="compare-pick-headline">${escapeHtml(pick.headline)}</p>
      ${pick.tradeoff ? `<p class="muted">${escapeHtml(pick.tradeoff)}</p>` : ""}
      ${scoreMeter(details, use)}
      ${edgeLists(details, use)}
      ${details.some(detail => !Object.keys(detail.specs).length) ? `<p class="muted">${escapeHtml(t("pick.missingSpecs"))}</p>` : ""}
    </div>`
    : `<p class="muted">${escapeHtml(t("use.prompt"))}</p>`;
  return `
    <section class="compare-pick" id="comparePick" aria-labelledby="comparePickTitle" aria-live="polite">
      <div class="compare-pick-head">
        <h2 id="comparePickTitle">${escapeHtml(use ? t("pick.titleFor", { use: t(`use.${use.key}.for`) }) : t("pick.title"))}</h2>
        <button class="small-button" type="button" data-share>${escapeHtml(t("compare.share"))}</button>
      </div>
      ${usePicker(use)}
      ${result}
    </section>`;
}

function drawPick(details) {
  const focused = document.activeElement?.closest?.("#comparePick [data-use]")?.dataset.use;
  $("#comparePick").outerHTML = pickBox(details);
  if (focused) $(`#comparePick [data-use="${focused}"]`).focus();
}

function choosePick(useKey) {
  saveUse(useKey);
  drawPick(shownDetails);
}

let renderToken = 0;
// The phones on screen, so choosing a use redraws the pick without refetching.
let shownDetails = null;

/*
 * Build the comparison off-screen and wait for its images to decode before showing it:
 * swapping in fresh <img>s directly paints them blank for a frame, so the result blinks.
 */
async function drawComparison(details, token = ++renderToken) {
  const next = document.createElement("div");
  next.innerHTML = comparisonHtml(details);
  const decoded = [...next.querySelectorAll("img")].map(image => image.decode().catch(() => {}));
  await Promise.race([Promise.all(decoded), new Promise(resolve => setTimeout(resolve, 1000))]);
  if (token !== renderToken) return;
  shownDetails = details;
  const result = $("#compareResult");
  result.removeAttribute("aria-busy");
  result.replaceChildren(...next.childNodes);
}

function comparisonHtml(details) {
  return `
    <div class="compare-cards">${details.map(summaryCard).join("")}</div>
    <h2>${escapeHtml(t("compare.specs"))}</h2>
    ${specTable(details)}
    <h2>${escapeHtml(t("stores.title"))}</h2>
    ${storeTable(details)}
    ${pickBox(details)}
    <h2>${escapeHtml(t("compare.history"))}</h2>
    ${historyChart(details)}`;
}

// A message in place of the comparison; it also cancels any comparison still loading.
function showMessage(text, extra = "") {
  renderToken++;
  shownDetails = null;
  const result = $("#compareResult");
  result.removeAttribute("aria-busy");
  result.innerHTML = `<p class="empty-inline">${escapeHtml(text)}</p>${extra}`;
}

// The address bar holds both phones and the use, so the link reopens this exact comparison.
async function copyLink(button) {
  const url = window.location.href;
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    window.prompt(t("compare.copyManually"), url);
    return;
  }
  button.textContent = t("compare.copied");
  setTimeout(() => { button.textContent = t("compare.share"); }, 2000);
}

/* ---------- suggestions ---------- */

// "iPhone 17 Pro eSIM" is the same phone as "iPhone 17 Pro" for comparing.
const family = model => model.replace(/\s+eSIM$/i, "");

// The cheapest in-stock phone of each family, cheapest first; the plain model over its eSIM one.
function familyPhones() {
  const cheapest = new Map();
  const rank = product => [product.model !== family(product.model), priceOf(product)];
  for (const product of state.products.filter(inStock)) {
    const current = cheapest.get(family(product.model));
    const [esim, price] = rank(product);
    if (!current || esim < rank(current)[0] || (esim === rank(current)[0] && price < rank(current)[1])) {
      cheapest.set(family(product.model), product);
    }
  }
  return [...cheapest.values()].sort((x, y) => priceOf(x) - priceOf(y));
}

const SUGGESTIONS_SHOWN = 4;

/*
 * With one phone chosen: the other families closest to it in price. With none: the
 * neighbouring families whose prices are closest, the hardest calls to make alone.
 */
function suggestions(ids) {
  const phones = familyPhones();
  const chosenSide = ids.findIndex(id => id != null);
  let pairs;
  let title;
  if (chosenSide >= 0) {
    const chosen = productById(ids[chosenSide]);
    title = t("compare.rivals", { name: productName(chosen) });
    pairs = phones
      .filter(product => family(product.model) !== family(chosen.model))
      .sort((x, y) => Math.abs(priceOf(x) - priceOf(chosen)) - Math.abs(priceOf(y) - priceOf(chosen)))
      .slice(0, SUGGESTIONS_SHOWN)
      .map(rival => ({ ids: chosenSide === 0 ? [chosen.id, rival.id] : [rival.id, chosen.id], label: t("compare.vsOne", { name: productName(rival) }) }));
  } else {
    title = t("compare.suggested");
    const gap = ([x, y]) => (priceOf(y) - priceOf(x)) / priceOf(x);
    pairs = phones.slice(1).map((product, index) => [phones[index], product])
      .sort((x, y) => gap(x) - gap(y))
      .slice(0, SUGGESTIONS_SHOWN)
      .map(pair => ({ ids: pair.map(product => product.id), label: pair.map(productName).join(" vs ") }));
  }
  if (!pairs.length) return "";
  return `
    <div class="compare-suggestions">
      <p class="pick-label">${escapeHtml(title)}</p>
      <div class="chip-row">${pairs.map(pair => `
        <button class="chip" type="button" data-pair="${pair.ids.join(",")}">${escapeHtml(pair.label)}</button>`).join("")}
      </div>
    </div>`;
}

function setPair(ids) {
  saveSelection(ids);
  SIDES.forEach((side, index) => renderPicker(side, ids[index]));
  renderComparison(ids);
}

/*
 * Switching storage or color keeps the current comparison on screen until the new one is
 * ready, then swaps it in one go; only a first load shows "Loading…". The phone that
 * didn't change keeps the data already fetched for it.
 */
async function renderComparison(ids) {
  const result = $("#compareResult");
  const products = ids.map(productById);
  if (products.some(product => !product)) return showMessage(t("compare.prompt"), suggestions(ids));
  if (products[0].id === products[1].id) return showMessage(t("compare.samePhone"));
  const token = ++renderToken;
  if (!shownDetails) result.innerHTML = `<p class="loading-state">${escapeHtml(t("loading"))}</p>`;
  result.setAttribute("aria-busy", "true");
  try {
    const details = await Promise.all(products.map(product =>
      shownDetails?.find(detail => detail.product === product) ?? productDetails(product)));
    // A newer pick replaced this one while it loaded.
    if (token !== renderToken) return;
    await drawComparison(details, token);
  } catch (error) {
    if (token === renderToken) showMessage(error.message);
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

// Redraw the phones already on screen in the new language. Refetching would swap in a
// short "Loading…" line first, and the page shrinking under it scrolls you to the top.
onLanguageChange(() => {
  if (state.currentPage !== "compare" || !state.products.length) return;
  const ids = pickerIds();
  SIDES.forEach((side, index) => renderPicker(side, ids[index]));
  const shown = shownDetails?.map(detail => detail.product.id);
  if (shown && shown.every((id, index) => id === ids[index])) drawComparison(shownDetails);
  else renderComparison(ids);
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
    // Emptying the box (typing it away or its × button) drops that phone from the comparison
    // and the address bar, so a refresh doesn't bring it back.
    $(`#compare-${side}-search`).addEventListener("input", event => {
      if (!event.target.value.trim() && pickerIds()[SIDES.indexOf(side)] != null) setSide(side, null);
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
    const useButton = event.target.closest("[data-use]");
    if (useButton && shownDetails) return choosePick(useButton.dataset.use);
    const shareButton = event.target.closest("[data-share]");
    if (shareButton) return copyLink(shareButton);
    const pairButton = event.target.closest("[data-pair]");
    if (pairButton) return setPair(pairButton.dataset.pair.split(",").map(Number));
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
