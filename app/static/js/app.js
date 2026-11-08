/* Connect the page controls to their feature modules. */
import { $, $$, pageFromLocation, productIdFromLocation, showPage, state } from "./core.js";
import { applyFilters, closeProductDetail, loadProducts, openProductDetail, openProductInCatalog, renderOverview, renderProducts, searchSuggestions, syncProductsView, updateSelectedActions } from "./catalog.js";
import { attachSuggestions } from "./combobox.js";
import { loadTracked, logout, track } from "./account.js";
import { bindDialogs, confirmEmailFromLink, openAlert, openAuth, openEmailSettings, openPasswordResetFromLink } from "./dialogs.js";
import { bindRefresh, loadRefreshStatus } from "./refresh.js";
import { onLanguageChange, switchLanguage, t, translatePage } from "./i18n.js";
import { bindCompare, renderComparePage } from "./compare.js";

function bindSearchAndCatalog() {
  const search = () => {
    state.searchQuery = $("#searchInput").value.trim();
    applyFilters();
  };
  // A search that leaves one phone opens it; otherwise the grid shows the matches.
  const searchAndOpenFirst = () => {
    search();
    if (state.visibleProducts.length === 1) openProductDetail(state.visibleProducts[0].id);
  };
  $("#searchForm").addEventListener("submit", event => {
    event.preventDefault();
    searchAndOpenFirst();
  });
  // Choosing a hint is an explicit search, like pressing the button.
  attachSuggestions($("#searchInput"), {
    suggest: searchSuggestions,
    onPick: item => {
      $("#searchInput").value = item.value;
      searchAndOpenFirst();
    },
  });
  // Typing alone doesn't search; only an emptied box (e.g. its × button) brings back every phone.
  $("#searchInput").addEventListener("input", () => {
    if (!$("#searchInput").value.trim() && state.searchQuery) search();
  });
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
    if (card) openProductDetail(card.dataset.productId);
  });
  $("#productGrid").addEventListener("keydown", event => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-product-id]")) {
      event.preventDefault();
      openProductDetail(event.target.dataset.productId);
    }
  });
  // Today page: a model row opens the catalog filtered to that model, on its cheapest variant.
  const openModel = row => openProductInCatalog(row.dataset.productId);
  $("#modelPricesToggle").addEventListener("click", () => {
    state.modelsExpanded = !state.modelsExpanded;
    renderOverview();
    // Folding up from the bottom of a long list: bring its top back into view.
    if (!state.modelsExpanded) $("#modelPrices").closest(".section").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  ["#modelPrices", "#weeklyDrops", "#dayChanges"].forEach(selector => {
    $(selector).addEventListener("click", event => {
      const row = event.target.closest(".model-price");
      if (row) openModel(row);
    });
    $(selector).addEventListener("keydown", event => {
      if ((event.key === "Enter" || event.key === " ") && event.target.matches(".model-price")) {
        event.preventDefault();
        openModel(event.target);
      }
    });
  });
  $("#backToGrid").addEventListener("click", closeProductDetail);
  $("#selectedTrackButton").addEventListener("click", () => state.selectedId && track(state.selectedId));
  $("#selectedAlertButton").addEventListener("click", () => state.selectedId && openAlert(state.selectedId));
}

function bindThemeToggle() {
  const button = $("#themeToggle");
  const applyTheme = theme => {
    const isDark = theme === "dark";
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    const label = t(isDark ? "theme.toLight" : "theme.toDark");
    button.setAttribute("aria-label", label);
    button.title = label;
    button.innerHTML = `<svg aria-hidden="true"><use href="#${isDark ? "i-sun" : "i-moon"}"/></svg>`;
  };
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  onLanguageChange(() => applyTheme(document.documentElement.dataset.theme));
  button.addEventListener("click", () => {
    const nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    const swap = () => applyTheme(nextTheme);
    const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!document.startViewTransition || reduceMotion) {
      swap();
    } else {
      // The new theme spreads out from the button like ink, instead of snapping.
      const { left, top, width, height } = button.getBoundingClientRect();
      const x = left + width / 2;
      const y = top + height / 2;
      // Overshoot the farthest corner (bottom-left) so it is covered well before the
      // animation's slow finish, instead of keeping the old color until the very end.
      const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y)) * 1.4;
      document.startViewTransition(swap).ready.then(() => {
        document.documentElement.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
          { duration: 600, easing: "cubic-bezier(.65, 0, .35, 1)", pseudoElement: "::view-transition-new(root)" },
        );
      }).catch(() => {
        // Transition skipped (e.g. tab hidden): the theme has still been applied.
      });
    }
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
      if (pageLink.dataset.pageLink === "compare") renderComparePage();
      syncProductsView();
      if (pageLink.hasAttribute("data-focus-search")) {
        requestAnimationFrame(() => $("#searchInput")?.focus());
      }
      return;
    }
    if (event.target.closest("[data-open-auth]")) openAuth();
  });
  window.addEventListener("popstate", () => {
    showPage(pageFromLocation());
    if (state.currentPage === "compare") renderComparePage();
    syncProductsView();
  });
}

translatePage();
delete document.documentElement.dataset.translating;
$("#langToggle").addEventListener("click", switchLanguage);
bindSearchAndCatalog();
bindThemeToggle();
bindAccountMenu();
bindNavigation();
bindDialogs();
bindRefresh();
bindCompare();
showPage(pageFromLocation());
// A shared phone link (/?page=products&id=9) opens that phone.
function openLinkedProduct() {
  const productId = productIdFromLocation();
  if (state.currentPage === "products" && productId) openProductInCatalog(productId, { updateHistory: false });
}

loadProducts().then(() => {
  if (state.currentPage === "compare") renderComparePage();
  openLinkedProduct();
});
loadRefreshStatus();
loadTracked();
updateSelectedActions();
confirmEmailFromLink();
openPasswordResetFromLink();
