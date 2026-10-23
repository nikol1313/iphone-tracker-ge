/* Connect the page controls to their feature modules. */
import { $, $$, pageFromLocation, showPage, state } from "./core.js";
import { loadProducts, renderProducts, selectProduct, updateSelectedActions } from "./catalog.js?v=20261018-12";
import { loadTracked, logout, track } from "./account.js";
import { bindDialogs, openAlert, openAuth, openEmailSettings, openTelegramSettings } from "./dialogs.js?v=20261018-1";
import { bindRefresh, loadRefreshStatus } from "./refresh.js?v=20261023-1";

function bindSearchAndCatalog() {
  $("#searchForm").addEventListener("submit", event => {
    event.preventDefault();
    const query = $("#searchInput").value.trim();
    if (query.length >= 2) loadProducts(query, { focusFirst: true });
  });
  $("#clearSearch").addEventListener("click", () => {
    $("#searchInput").value = "";
    loadProducts();
  });
  $("#showMoreButton").addEventListener("click", () => {
    state.visibleCount += 12;
    renderProducts();
  });
  $("#showLessButton").addEventListener("click", () => {
    state.visibleCount = 8;
    renderProducts();
    $("#productsTitle").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#productGrid").addEventListener("click", event => {
    const card = event.target.closest("[data-product-id]");
    if (card) selectProduct(card.dataset.productId, { scroll: true });
  });
  $("#productGrid").addEventListener("keydown", event => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-product-id]")) {
      event.preventDefault();
      selectProduct(event.target.dataset.productId, { scroll: true });
    }
  });
  $("#selectedTrackButton").addEventListener("click", () => state.selectedId && track(state.selectedId));
  $("#selectedAlertButton").addEventListener("click", () => state.selectedId && openAlert(state.selectedId));
}

function bindThemeToggle() {
  const button = $("#themeToggle");
  const applyTheme = theme => {
    const isDark = theme === "dark";
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    button.setAttribute("aria-label", `Switch to ${isDark ? "light" : "dark"} theme`);
    button.title = `Switch to ${isDark ? "light" : "dark"} theme`;
    button.innerHTML = `<svg aria-hidden="true"><use href="#${isDark ? "i-sun" : "i-moon"}"/></svg>`;
  };
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  button.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(nextTheme);
    try {
      localStorage.setItem("priceMonitorTheme", nextTheme);
    } catch {
      // Theme still applies for this page if storage is unavailable.
    }
  });
}

function bindAccountMenu() {
  $("#trackedContent").addEventListener("click", event => {
    const untrack = event.target.closest("[data-untrack]");
    if (untrack) track(untrack.dataset.untrack);
    if (event.target.closest("[data-open-auth]")) openAuth();
  });
  $("#accountButton").addEventListener("click", () => {
    const menu = $("#accountMenu");
    menu.hidden = !menu.hidden;
    $("#accountButton").setAttribute("aria-expanded", String(!menu.hidden));
  });
  $("#signOutButton").addEventListener("click", () => logout());
  $("#signInMenuButton").addEventListener("click", () => {
    $("#accountMenu").hidden = true;
    $("#accountButton").setAttribute("aria-expanded", "false");
    openAuth();
  });
  $("[data-notification=telegram]").addEventListener("click", openTelegramSettings);
  $("[data-notification=email]").addEventListener("click", openEmailSettings);
  document.addEventListener("click", event => {
    if (!event.target.closest(".account-actions")) {
      $("#accountMenu").hidden = true;
      $("#accountButton").setAttribute("aria-expanded", "false");
    }
  });
}

function bindNavigation() {
  document.addEventListener("click", event => {
    const pageLink = event.target.closest("[data-page-link]");
    if (pageLink && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      showPage(pageLink.dataset.pageLink, true);
      if (pageLink.hasAttribute("data-focus-search")) {
        requestAnimationFrame(() => $("#searchInput")?.focus());
      }
      return;
    }
    if (event.target.closest("[data-open-auth]")) openAuth();
  });
  window.addEventListener("popstate", () => showPage(pageFromLocation()));
}

bindSearchAndCatalog();
bindThemeToggle();
bindAccountMenu();
bindNavigation();
bindDialogs();
bindRefresh();
showPage(pageFromLocation());
loadProducts();
loadRefreshStatus();
loadTracked();
updateSelectedActions();
