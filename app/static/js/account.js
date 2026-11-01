/* Sign-in state, tracked products, and profile actions. */
import { $, api, escapeHtml, money, productName, showToast, state, variant } from "./core.js";
import { renderProducts, updateSelectedActions } from "./catalog.js";
import { onLanguageChange, t } from "./i18n.js";

export async function loadTracked() {
  updateAccount();
  if (!state.token) {
    state.tracked = [];
    return;
  }
  try {
    const page = await api("/tracked-products?limit=100");
    state.tracked = Array.isArray(page.items) ? page.items : [];
    renderTracked();
    renderProducts();
    updateSelectedActions();
  } catch (error) {
    if (error.status === 401) logout(false);
    else showToast(error.message);
  }
}

export function renderTracked() {
  const content = $("#trackedContent");
  if (!state.tracked.length) {
    content.innerHTML = `<p>${t("alerts.empty")}</p>`;
    return;
  }
  content.innerHTML = `<div class="tracked-list">${state.tracked.map(item => `
    <div class="tracked-row">
      <div><h3>${escapeHtml(productName(item.product))}</h3><p>${escapeHtml(variant(item.product))}</p></div>
      <div>
        <p><span class="tracked-price">${escapeHtml(money(item.product.lowest_price, item.product.currency || "GEL"))}</span> ${item.product.available_listing_count > 0 ? t("alerts.cheapestNow") : t("alerts.lastListed")}</p>
        ${item.active_alert
          ? `<p class="alert-value${item.active_alert.is_triggered ? " reached" : ""}">${escapeHtml(item.active_alert.target_price == null ? t("alerts.alertStock") : t("alerts.alertAt", { amount: money(item.active_alert.target_price, item.active_alert.currency) }))}${item.active_alert.is_triggered ? t("alerts.reached") : ""}</p>`
          : `<p>${t("alerts.none")}</p>`}
      </div>
      <div class="tracked-actions">
        <button class="small-button" type="button" data-edit-alert="${item.product.id}">${item.active_alert ? t("detail.editAlert") : t("detail.setAlert")}</button>
        <button class="small-button" type="button" data-untrack="${item.product.id}">${t("detail.stopTracking")}</button>
      </div>
    </div>`).join("")}</div>`;
}

onLanguageChange(() => {
  updateAccount();
  if (state.token) renderTracked();
});

export function updateAccount() {
  const button = $("#accountButton");
  const menuName = $("#accountMenuName");
  if (state.token) {
    const name = state.email || "?";
    button.innerHTML = `<span class="profile-avatar" aria-hidden="true">${escapeHtml(name.slice(0, 1).toUpperCase())}</span><svg aria-hidden="true"><use href="#i-chevron"/></svg>`;
    button.classList.add("signed-in");
    button.setAttribute("aria-label", t("account.menuFor", { name }));
    button.setAttribute("aria-haspopup", "true");
    menuName.textContent = name;
  } else {
    button.innerHTML = `<svg aria-hidden="true"><use href="#i-user"/></svg><span>${t("account.signIn")}</span>`;
    button.classList.remove("signed-in");
    button.removeAttribute("aria-label");
    button.removeAttribute("aria-haspopup");
    $("#trackedContent").innerHTML = `<p>${t("alerts.signInPrompt")}</p><button class="primary-button" type="button" data-open-auth>${t("account.signIn")}</button>`;
  }
}

export async function track(productId) {
  if (!state.token) {
    $("#authError").textContent = "";
    $("#authDialog").showModal();
    showToast(t("track.signIn"));
    return;
  }
  const tracked = state.tracked.some(item => item.product.id === Number(productId));
  try {
    if (tracked) await api(`/tracked-products/${productId}`, { method: "DELETE" });
    else await api("/tracked-products", { method: "POST", body: JSON.stringify({ product_id: Number(productId) }) });
    showToast(tracked ? t("track.removed") : t("track.added"));
    await loadTracked();
  } catch (error) {
    showToast(error.message);
  }
}

export function logout(notify = true) {
  state.token = null;
  state.email = null;
  state.tracked = [];
  sessionStorage.removeItem("priceMonitorToken");
  sessionStorage.removeItem("priceMonitorEmail");
  updateAccount();
  renderProducts();
  updateSelectedActions();
  $("#accountMenu").hidden = true;
  $("#accountButton").setAttribute("aria-expanded", "false");
  if (notify) showToast(t("auth.signedOut"));
}
