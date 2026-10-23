/* Manual price refresh with the shared one-hour cooldown. */
import { $, api, showToast, state } from "./core.js";
import { loadProducts } from "./catalog.js?v=20261018-12";
import { openAuth } from "./dialogs.js?v=20261018-1";

const refresh = { lastRefreshedAt: null, availableAt: null, running: false };

const relative = value => {
  const minutes = Math.round((new Date(value) - Date.now()) / 60000);
  if (Math.abs(minutes) < 1) return "just now";
  const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  return Math.abs(minutes) < 60
    ? format.format(minutes, "minute")
    : format.format(Math.round(minutes / 60), "hour");
};

function renderRefresh() {
  const button = $("#refreshButton");
  const coolingDown = refresh.availableAt && new Date(refresh.availableAt) > Date.now();
  button.disabled = refresh.running || Boolean(coolingDown);
  $("span", button).textContent = refresh.running ? "Refreshing…" : "Refresh prices";
  const parts = [];
  if (refresh.lastRefreshedAt) parts.push(`Updated ${relative(refresh.lastRefreshedAt)}`);
  if (coolingDown && !refresh.running) parts.push(`next refresh ${relative(refresh.availableAt)}`);
  $("#refreshStatus").textContent = parts.join(" · ");
}

function applyStatus(status) {
  refresh.lastRefreshedAt = status.last_refreshed_at;
  refresh.availableAt = status.next_manual_refresh_at;
  renderRefresh();
}

export async function loadRefreshStatus() {
  try {
    applyStatus(await api("/refresh"));
  } catch {
    $("#refreshStatus").textContent = "";
  }
}

async function refreshPrices() {
  if (!state.token) {
    showToast("Sign in to refresh prices");
    openAuth();
    return;
  }
  refresh.running = true;
  renderRefresh();
  try {
    const result = await api("/refresh", { method: "POST" });
    applyStatus(result);
    showToast(result.failed_stores.length
      ? `Prices updated · ${result.failed_stores.join(", ")} unavailable`
      : "Prices updated from all stores");
    loadProducts(state.searchQuery || "");
  } catch (error) {
    showToast(error.message);
    await loadRefreshStatus();
  } finally {
    refresh.running = false;
    renderRefresh();
  }
}

export function bindRefresh() {
  $("#refreshButton").addEventListener("click", refreshPrices);
  setInterval(renderRefresh, 30000);
}
