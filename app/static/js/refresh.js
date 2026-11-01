/* Manual price refresh with the shared one-hour cooldown. */
import { $, api, relativeTime as relative, showToast, state } from "./core.js";
import { loadProducts, renderOverview } from "./catalog.js";
import { openAuth } from "./dialogs.js";
import { t } from "./i18n.js";

const refresh = { lastRefreshedAt: null, availableAt: null, running: false };

function renderRefresh() {
  const button = $("#refreshButton");
  const coolingDown = refresh.availableAt && new Date(refresh.availableAt) > Date.now();
  button.disabled = refresh.running || Boolean(coolingDown);
  $("span", button).textContent = refresh.running ? t("refresh.running") : t("refresh.button");
  const parts = [];
  if (refresh.lastRefreshedAt) parts.push(t("refresh.updated", { time: relative(refresh.lastRefreshedAt) }));
  if (coolingDown && !refresh.running) parts.push(t("refresh.next", { time: relative(refresh.availableAt) }));
  $("#refreshStatus").textContent = parts.join(" · ");
}

function applyStatus(status) {
  refresh.lastRefreshedAt = status.last_refreshed_at;
  refresh.availableAt = status.next_manual_refresh_at;
  state.lastRefreshedAt = status.last_refreshed_at;
  renderRefresh();
  renderOverview();
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
    showToast(t("refresh.signIn"));
    openAuth();
    return;
  }
  refresh.running = true;
  renderRefresh();
  try {
    const result = await api("/refresh", { method: "POST" });
    applyStatus(result);
    showToast(result.failed_stores.length
      ? t("refresh.partial", { stores: result.failed_stores.join(", ") })
      : t("refresh.done"));
    loadProducts();
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
