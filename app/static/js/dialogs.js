/* Authentication, price alert, and notification forms. */
import { $, $$, api, money, showToast, state } from "./core.js";
import { loadTracked } from "./account.js";

export function openAuth() {
  $("#authError").textContent = "";
  $("#authDialog").showModal();
}

export function openAlert(productId) {
  if (!state.token) {
    openAuth();
    showToast("Sign in before creating an alert.");
    return;
  }
  const product = state.products.find(item => item.id === Number(productId))
    || state.tracked.find(item => item.product.id === Number(productId))?.product;
  if (!product) return;
  $("#alertTitle").textContent = `${product.model} target`;
  const form = $("#alertForm");
  form.product_id.value = product.id;
  form.currency.value = product.currency === "USD" ? "USD" : "GEL";
  form.target_price.value = product.lowest_price || "";
  $("#alertCurrentPrice").textContent = product.lowest_price == null
    ? "No store has a price for this iPhone right now."
    : `Best price right now: ${money(product.lowest_price, product.currency || "GEL")}. Set a lower target to wait for a drop.`;
  $("#alertEmailNote").textContent = "";
  $("#alertError").textContent = "";
  $("#alertDialog").showModal();
  api("/notification-settings/email").then(settings => {
    $("#alertEmailNote").textContent = settings.notification_email
      ? `We’ll email ${settings.notification_email}.`
      : "Add your email in the account menu (Email alerts) so we can reach you.";
  }).catch(() => {});
}

export async function openEmailSettings() {
  closeAccountMenu();
  if (!state.token) {
    openAuth();
    showToast("Sign in to set up email alerts.");
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
    $("#emailDeliveryWarning").hidden = settings.delivery_configured;
    $("#emailTestButton").disabled = !settings.notification_email || !settings.delivery_configured;
  } catch (error) {
    $("#emailError").textContent = error.message;
  }
}

function closeAccountMenu() {
  $("#accountMenu").hidden = true;
  $("#accountButton").setAttribute("aria-expanded", "false");
}

function bindAuthentication() {
  $("#authMode").addEventListener("click", () => {
    state.authMode = state.authMode === "login" ? "register" : "login";
    const registering = state.authMode === "register";
    $("#authTitle").textContent = registering ? "Create account" : "Sign in";
    $("#authForm button[type=submit]").textContent = registering ? "Create account" : "Sign in";
    $("#authMode").textContent = registering ? "Already have an account? Sign in" : "Create an account";
    $("#authError").textContent = "";
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
      showToast(state.authMode === "register" ? "Account created and signed in." : "Signed in.");
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

  $("#alertForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    $("#alertError").textContent = "";
    try {
      await api(`/products/${form.get("product_id")}/alerts`, {
        method: "POST",
        body: JSON.stringify({ target_price: form.get("target_price"), currency: form.get("currency") }),
      });
      $("#alertDialog").close();
      const settings = await api("/notification-settings/email").catch(() => null);
      const target = money(form.get("target_price"), form.get("currency"));
      showToast(settings && !settings.notification_email
        ? `Alert set for ${target}. Add your email in the account menu to get notified.`
        : `Alert set: we’ll email you when it drops to ${target} or lower.`);
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
      $("#emailDialog").close();
      showToast(settings.notification_email
        ? `Saved. Price alerts will be emailed to ${settings.notification_email}.`
        : "Email alerts are turned off.");
    } catch (error) {
      setMessages(error.message);
    }
  });
  $("#emailTestButton").addEventListener("click", async () => {
    setMessages();
    const button = $("#emailTestButton");
    button.disabled = true;
    try {
      await api("/notification-settings/email/test", { method: "POST" });
      setMessages("", `Test email sent to ${state.notificationSettings.notification_email}. Check your inbox and spam folder.`);
    } catch (error) {
      setMessages(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

export function bindDialogs() {
  $("#closeAuth").addEventListener("click", () => $("#authDialog").close());
  $("#closeAlert").addEventListener("click", () => $("#alertDialog").close());
  $("#closeEmail").addEventListener("click", () => $("#emailDialog").close());
  bindAuthentication();
  bindAlertForm();
  bindEmailForm();
}
