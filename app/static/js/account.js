/* Sign-in state, tracked products, and profile actions. */
import { $, api, escapeHtml, money, productName, showToast, state, variant } from "./core.js";
import { renderProducts, updateSelectedActions } from "./catalog.js";

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
    content.innerHTML = "<p>You are signed in. Track a product to keep it in this list.</p>";
    return;
  }
  content.innerHTML = `<div class="tracked-list">${state.tracked.map(item => `
    <div class="tracked-row">
      <div><h3>${escapeHtml(productName(item.product))}</h3><p>${escapeHtml(variant(item.product))}</p></div>
      <div>
        <p>${escapeHtml(money(item.product.lowest_price, item.product.currency || "GEL"))} ${item.product.available_listing_count > 0 ? "best available" : "last listed"}</p>
        ${item.active_alert
          ? `<p class="alert-value">Email me at ${escapeHtml(money(item.active_alert.target_price, item.active_alert.currency))} or lower${item.active_alert.is_triggered ? " · Reached" : ""}</p>`
          : "<p>No active alert</p>"}
      </div>
      <button class="small-button" type="button" data-untrack="${item.product.id}">Stop tracking</button>
    </div>`).join("")}</div>`;
}

export function updateAccount() {
  const button = $("#accountButton");
  const menuName = $("#accountMenuName");
  const menuEmail = $("#accountMenuEmail");
  const avatar = $("#accountMenuAvatar");
  const signOut = $("#signOutButton");
  const signIn = $("#signInMenuButton");
  if (state.token) {
    const name = state.email || "Account";
    button.innerHTML = `<span class="profile-avatar" aria-hidden="true">${escapeHtml(name.slice(0, 1).toUpperCase())}</span>`;
    button.setAttribute("aria-label", `Account: ${name}`);
    menuName.textContent = name;
    menuEmail.textContent = "Signed in";
    avatar.textContent = name.slice(0, 1).toUpperCase();
    signOut.hidden = false;
    signIn.hidden = true;
  } else {
    button.innerHTML = '<span class="profile-avatar" aria-hidden="true"><svg><use href="#i-user"/></svg></span>';
    button.setAttribute("aria-label", "Account: sign in");
    menuName.textContent = "Guest";
    menuEmail.textContent = "Sign in to manage your account";
    avatar.textContent = "?";
    signOut.hidden = true;
    signIn.hidden = false;
    $("#trackedContent").innerHTML = '<p>Sign in to track products and create price alerts.</p><button class="primary-button" type="button" data-open-auth>Sign in</button>';
  }
}

export async function track(productId) {
  if (!state.token) {
    $("#authError").textContent = "";
    $("#authDialog").showModal();
    showToast("Sign in before tracking a product.");
    return;
  }
  const tracked = state.tracked.some(item => item.product.id === Number(productId));
  try {
    if (tracked) await api(`/tracked-products/${productId}`, { method: "DELETE" });
    else await api("/tracked-products", { method: "POST", body: JSON.stringify({ product_id: Number(productId) }) });
    showToast(tracked ? "Product removed from tracking." : "Product is now tracked.");
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
  if (notify) showToast("Signed out.");
}
