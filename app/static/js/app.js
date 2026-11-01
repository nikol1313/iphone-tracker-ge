/* Connect the page controls to their feature modules. */
import { $, $$, pageFromLocation, showPage, state } from "./core.js";
import { applyFilters, loadProducts, renderProducts, selectProduct, updateSelectedActions } from "./catalog.js";
import { loadTracked, logout, track } from "./account.js";
import { bindDialogs, confirmEmailFromLink, openAlert, openAuth, openEmailSettings, openPasswordResetFromLink } from "./dialogs.js";
import { bindRefresh, loadRefreshStatus } from "./refresh.js";

function bindSearchAndCatalog() {
  const search = () => {
    state.searchQuery = $("#searchInput").value.trim();
    applyFilters();
  };
  $("#searchForm").addEventListener("submit", event => {
    event.preventDefault();
    search();
    const first = state.visibleProducts[0];
    if (first) selectProduct(first.id, { scroll: true });
  });
  $("#searchInput").addEventListener("input", search);
  $("#clearFilters").addEventListener("click", () => {
    $("#searchInput").value = "";
    state.searchQuery = "";
    $("#modelFilter").value = "";
    $("#storageFilter").value = "";
    $("#inStockFilter").checked = false;
    applyFilters();
  });
  ["#modelFilter", "#storageFilter", "#sortSelect", "#inStockFilter"].forEach(selector => {
    $(selector).addEventListener("change", () => applyFilters());
  });
  $("#showMoreButton").addEventListener("click", () => {
    state.visibleCount += 12;
    renderProducts();
  });
  $("#showLessButton").addEventListener("click", () => {
    state.visibleCount = 12;
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
  // Today page: a model row opens the catalog filtered to that model, on its cheapest variant.
  const openModel = row => {
    $("#searchInput").value = "";
    state.searchQuery = "";
    $("#modelFilter").value = row.dataset.model;
    showPage("products", true);
    applyFilters();
    selectProduct(row.dataset.productId, { scroll: true });
  };
  $("#modelPrices").addEventListener("click", event => {
    const row = event.target.closest(".model-price");
    if (row) openModel(row);
  });
  $("#modelPrices").addEventListener("keydown", event => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches(".model-price")) {
      event.preventDefault();
      openModel(event.target);
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
    const editAlert = event.target.closest("[data-edit-alert]");
    if (editAlert) openAlert(editAlert.dataset.editAlert);
    if (event.target.closest("[data-open-auth]")) openAuth();
  });
  $("#accountButton").addEventListener("click", () => {
    // Signed out, the button is just "Sign in"; the menu is for signed-in accounts.
    if (!state.token) {
      openAuth();
      return;
    }
    const menu = $("#accountMenu");
    menu.hidden = !menu.hidden;
    $("#accountButton").setAttribute("aria-expanded", String(!menu.hidden));
  });
  $("#signOutButton").addEventListener("click", () => logout());
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
confirmEmailFromLink();
openPasswordResetFromLink();
