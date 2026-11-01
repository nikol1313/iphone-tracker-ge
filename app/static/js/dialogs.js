/* Authentication, price alert, and notification forms. */
import { $, $$, api, money, showToast, state } from "./core.js";
import { loadTracked } from "./account.js";
import { onLanguageChange, t } from "./i18n.js";

export function openAuth() {
  $("#authError").textContent = "";
  $("#authDialog").showModal();
}

/* Explain where alert emails go, or what is missing before they can be sent. */
export function emailStatusNote(settings) {
  if (!settings.notification_email) return t("alert.needEmail");
  if (!settings.email_verified) return t("alert.needConfirm", { email: settings.notification_email });
  return t("alert.willEmail", { email: settings.notification_email });
}

export function openAlert(productId) {
  if (!state.token) {
    openAuth();
    showToast(t("alert.signIn"));
    return;
  }
  const product = state.products.find(item => item.id === Number(productId))
    || state.tracked.find(item => item.product.id === Number(productId))?.product;
  if (!product) return;
  const alert = activeAlert(product.id);
  $("#alertTitle").textContent = t(alert ? "alert.titleEdit" : "alert.titleNew", { model: product.model });
  const form = $("#alertForm");
  form.product_id.value = product.id;
  form.alert_id.value = alert?.id ?? "";
  form.target_price.value = alert?.target_price || product.lowest_price || "";
  // Back in stock only makes sense while no store has it; then it's the natural default.
  const outOfStock = !(product.available_listing_count > 0);
  const stockAlert = alert ? alert.target_price == null : outOfStock;
  $("#alertKind").hidden = !outOfStock && !stockAlert;
  form.kind.value = stockAlert ? "stock" : "price";
  showAlertKind();
  $("#alertRemoveButton").hidden = !alert;
  $("#alertCurrentPrice").textContent = product.lowest_price == null
    ? t("alert.noPrice")
    : t("alert.bestNow", { price: money(product.lowest_price, product.currency || "GEL") });
  $("#alertEmailNote").textContent = "";
  $("#alertError").textContent = "";
  $("#alertDialog").showModal();
  api("/notification-settings/email").then(settings => {
    $("#alertEmailNote").textContent = emailStatusNote(settings);
  }).catch(() => {});
}

// Swap the target-price fields and explainer for the chosen kind of alert.
function showAlertKind() {
  const stock = $("#alertForm").kind.value === "stock";
  $("#alertPriceFields").hidden = stock;
  $("#alertTargetPrice").required = !stock;
  $("#alertExplainer").innerHTML = t(stock ? "alert.explainerStock" : "alert.explainer");
  const alertId = $("#alertForm").alert_id.value;
  $("#alertSubmit").textContent = alertId ? t("alert.submitEdit") : t(stock ? "alert.submitStock" : "alert.submitNew");
}

export const activeAlert = productId => state.tracked
  .find(item => item.product.id === Number(productId))?.active_alert || null;

export async function openEmailSettings() {
  closeAccountMenu();
  if (!state.token) {
    openAuth();
    showToast(t("email.signIn"));
    return;
  }
  const form = $("#emailForm");
  $("#emailError").textContent = "";
  $("#emailSuccess").textContent = "";
  $("#emailDialog").showModal();
  try {
    const settings = await api("/notification-settings/email");
    state.notificationSettings = settings;
    // Suggest the account email until the user picks an address.
    form.notification_email.value = settings.notification_email || state.email || "";
    renderEmailStatus(settings);
  } catch (error) {
    $("#emailError").textContent = error.message;
  }
}

function renderEmailStatus(settings) {
  const pending = Boolean(settings.notification_email) && !settings.email_verified;
  const status = $("#emailVerificationStatus");
  status.hidden = !settings.notification_email;
  status.textContent = pending
    ? t("email.pending", { email: settings.notification_email })
    : t("email.confirmed", { email: settings.notification_email });
  $("#emailDeliveryWarning").hidden = settings.delivery_configured;
  $("#emailVerifyButton").hidden = !pending;
  $("#emailVerifyButton").disabled = !settings.delivery_configured;
  $("#emailTestButton").disabled = !settings.email_verified || !settings.delivery_configured;
}

/* Finish the emailed confirmation link (/?verify_email=…) and drop the token from the address bar. */
export async function confirmEmailFromLink() {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("verify_email");
  if (!token) return;
  url.searchParams.delete("verify_email");
  window.history.replaceState(window.history.state, "", url);
  try {
    await api("/notification-settings/email/verify", { method: "POST", body: JSON.stringify({ token }) });
    showToast(t("email.verified"));
  } catch (error) {
    showToast(error.message);
  }
}

function closeAccountMenu() {
  $("#accountMenu").hidden = true;
  $("#accountButton").setAttribute("aria-expanded", "false");
}

/* Finish the emailed reset link (/?reset_password=…): drop the token from the address bar and ask for a new password. */
export function openPasswordResetFromLink() {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("reset_password");
  if (!token) return;
  url.searchParams.delete("reset_password");
  window.history.replaceState(window.history.state, "", url);
  state.resetToken = token;
  $("#resetError").textContent = "";
  $("#resetDialog").showModal();
}

function setAuthMode(mode) {
  state.authMode = mode;
  const registering = mode === "register";
  $("#authTitle").textContent = registering ? t("auth.createAccount") : t("auth.signIn");
  $("#authForm button[type=submit]").textContent = registering ? t("auth.createAccount") : t("auth.signIn");
  $("#authForm [name=password]").autocomplete = registering ? "new-password" : "current-password";
  $("#authMode").textContent = registering ? t("auth.haveAccount") : t("auth.createAnAccount");
  $("#forgotPasswordButton").hidden = registering;
  $("#authError").textContent = "";
}

function bindPasswordReset() {
  $("#forgotPasswordButton").addEventListener("click", () => {
    const email = $("#authForm [name=email]").value;
    $("#authDialog").close();
    $("#forgotForm [name=email]").value = email;
    $("#forgotError").textContent = "";
    $("#forgotSuccess").textContent = "";
    $("#forgotDialog").showModal();
  });
  $("#forgotForm").addEventListener("submit", async event => {
    event.preventDefault();
    const email = new FormData(event.currentTarget).get("email").trim();
    const submit = $("button[type=submit]", event.currentTarget);
    submit.disabled = true;
    $("#forgotError").textContent = "";
    $("#forgotSuccess").textContent = "";
    try {
      await api("/auth/password-reset", { method: "POST", body: JSON.stringify({ email }) });
      $("#forgotSuccess").textContent = t("forgot.sent", { email });
    } catch (error) {
      $("#forgotError").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
  $("#resetForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (form.get("password") !== form.get("confirm")) {
      $("#resetError").textContent = t("reset.mismatch");
      return;
    }
    const submit = $("button[type=submit]", event.currentTarget);
    submit.disabled = true;
    $("#resetError").textContent = "";
    try {
      await api("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token: state.resetToken, password: form.get("password") }),
      });
      state.resetToken = null;
      event.currentTarget.reset();
      $("#resetDialog").close();
      setAuthMode("login");
      openAuth();
      showToast(t("reset.done"));
    } catch (error) {
      $("#resetError").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
}

function bindAuthentication() {
  $("#authMode").addEventListener("click", () => {
    setAuthMode(state.authMode === "login" ? "register" : "login");
  });
  $("#authForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const credentials = { email: form.get("email"), password: form.get("password") };
    const submit = $("button[type=submit]", event.currentTarget);
    submit.disabled = true;
    $("#authError").textContent = "";
    try {
      if (state.authMode === "register") await api("/auth/register", { method: "POST", body: JSON.stringify(credentials) });
      const token = await api("/auth/login", { method: "POST", body: JSON.stringify(credentials) });
      state.token = token.access_token;
      state.email = credentials.email;
      sessionStorage.setItem("priceMonitorToken", state.token);
      sessionStorage.setItem("priceMonitorEmail", state.email);
      $("#authDialog").close();
      showToast(state.authMode === "register" ? t("auth.created") : t("auth.signedIn"));
      await loadTracked();
    } catch (error) {
      $("#authError").textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  });
}

function bindAlertForm() {
  const priceInput = $("#alertForm [name=target_price]");
  const adjustPrice = direction => {
    const currentPrice = Number(priceInput.value);
    const current = Number.isFinite(currentPrice) ? currentPrice : 0;
    // Snap to round hundreds: 6500 → 6400, 6449.99 → 6400 going down.
    const next = direction > 0
      ? Math.floor(current / 100) * 100 + 100
      : Math.ceil(current / 100) * 100 - 100;
    if (next < 100) return;
    priceInput.value = next.toFixed(2);
    priceInput.dispatchEvent(new Event("input", { bubbles: true }));
  };
  $$("[data-price-step]").forEach(button => button.addEventListener("click", () => {
    adjustPrice(Number(button.dataset.priceStep));
  }));
  priceInput.addEventListener("wheel", event => {
    event.preventDefault();
    adjustPrice(event.deltaY < 0 ? 1 : -1);
  }, { passive: false });
  priceInput.addEventListener("keydown", event => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    adjustPrice(event.key === "ArrowUp" ? 1 : -1);
  });

  $$("#alertKind input").forEach(radio => radio.addEventListener("change", showAlertKind));
  $("#alertForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    $("#alertError").textContent = "";
    const alertId = form.get("alert_id");
    const stock = form.get("kind") === "stock";
    try {
      await api(alertId ? `/alerts/${alertId}` : `/products/${form.get("product_id")}/alerts`, {
        method: alertId ? "PUT" : "POST",
        body: JSON.stringify({ target_price: stock ? null : form.get("target_price") }),
      });
      $("#alertDialog").close();
      const settings = await api("/notification-settings/email").catch(() => null);
      const target = stock ? t("alert.whenBack") : money(form.get("target_price"));
      const action = alertId ? t("alert.updated") : t("alert.set");
      showToast(settings && !settings.email_verified
        ? t("alert.savedPending", { action, target, note: emailStatusNote(settings) })
        : stock ? t("alert.savedStock", { action }) : t("alert.saved", { action, target }));
      await loadTracked();
    } catch (error) {
      $("#alertError").textContent = error.message;
    }
  });
  $("#alertRemoveButton").addEventListener("click", async () => {
    const alertId = $("#alertForm").alert_id.value;
    $("#alertError").textContent = "";
    try {
      await api(`/alerts/${alertId}`, { method: "DELETE" });
      $("#alertDialog").close();
      showToast(t("alert.removed"));
      await loadTracked();
    } catch (error) {
      $("#alertError").textContent = error.message;
    }
  });
}

function bindEmailForm() {
  const setMessages = (error = "", success = "") => {
    $("#emailError").textContent = error;
    $("#emailSuccess").textContent = success;
  };
  $("#emailForm").addEventListener("submit", async event => {
    event.preventDefault();
    const email = new FormData(event.currentTarget).get("notification_email").trim();
    setMessages();
    try {
      const settings = await api("/notification-settings/email", {
        method: "PUT",
        body: JSON.stringify({ notification_email: email || null }),
      });
      state.notificationSettings = settings;
      renderEmailStatus(settings);
      if (!settings.notification_email) {
        $("#emailDialog").close();
        showToast(t("email.off"));
      } else if (settings.email_verified) {
        $("#emailDialog").close();
        showToast(t("email.saved", { email: settings.notification_email }));
      } else if (settings.delivery_configured) {
        await sendConfirmation();
      }
    } catch (error) {
      setMessages(error.message);
    }
  });
  const sendConfirmation = async () => {
    const button = $("#emailVerifyButton");
    button.disabled = true;
    try {
      await api("/notification-settings/email/verification", { method: "POST" });
      setMessages("", t("email.linkSent", { email: state.notificationSettings.notification_email }));
    } catch (error) {
      setMessages(error.message);
    } finally {
      button.disabled = false;
    }
  };
  $("#emailVerifyButton").addEventListener("click", () => {
    setMessages();
    sendConfirmation();
  });
  $("#emailTestButton").addEventListener("click", async () => {
    setMessages();
    const button = $("#emailTestButton");
    button.disabled = true;
    try {
      await api("/notification-settings/email/test", { method: "POST" });
      setMessages("", t("email.testSent", { email: state.notificationSettings.notification_email }));
    } catch (error) {
      setMessages(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

onLanguageChange(() => {
  setAuthMode(state.authMode);
  if (state.notificationSettings && $("#emailDialog").open) renderEmailStatus(state.notificationSettings);
  if ($("#alertDialog").open) showAlertKind();
});

export function bindDialogs() {
  $("#closeAuth").addEventListener("click", () => $("#authDialog").close());
  $("#closeAlert").addEventListener("click", () => $("#alertDialog").close());
  $("#closeEmail").addEventListener("click", () => $("#emailDialog").close());
  $("#closeForgot").addEventListener("click", () => $("#forgotDialog").close());
  $("#closeReset").addEventListener("click", () => $("#resetDialog").close());
  bindAuthentication();
  bindPasswordReset();
  bindAlertForm();
  bindEmailForm();
}
