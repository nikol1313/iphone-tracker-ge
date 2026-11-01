/* A text input with a suggestion list: type to filter, arrows/Enter/Escape or tap to choose. */
import { escapeHtml } from "./core.js";

let comboboxCount = 0;

/*
 * suggest(query) returns [{ label, detail?, value }]; onPick(item) runs when one is chosen.
 * Enter with nothing highlighted is left to the surrounding form (e.g. submitting a search).
 */
export function attachSuggestions(input, { suggest, onPick }) {
  const id = `suggestions-${++comboboxCount}`;
  const list = document.createElement("ul");
  list.className = "suggestions";
  list.id = id;
  list.setAttribute("role", "listbox");
  list.hidden = true;
  input.after(list);
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", id);
  input.setAttribute("aria-expanded", "false");
  input.autocomplete = "off";

  let items = [];
  let active = -1;

  const close = () => {
    list.hidden = true;
    active = -1;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  };

  const render = () => {
    items = suggest(input.value.trim());
    if (!items.length) {
      close();
      return;
    }
    active = Math.min(active, items.length - 1);
    list.innerHTML = items.map((item, index) => `
      <li role="option" id="${id}-${index}" data-index="${index}" aria-selected="${index === active}">
        <span>${escapeHtml(item.label)}</span>${item.detail ? `<small>${escapeHtml(item.detail)}</small>` : ""}
      </li>`).join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    if (active >= 0) {
      input.setAttribute("aria-activedescendant", `${id}-${active}`);
      list.children[active].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  };

  const pick = index => {
    const item = items[index];
    close();
    if (item) onPick(item);
  };

  input.addEventListener("input", () => {
    active = -1;
    render();
  });
  input.addEventListener("focus", () => {
    if (input.value.trim()) render();
  });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", event => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (list.hidden) {
        render();
        return;
      }
      // Cycle through -1 (nothing highlighted, the typed text stands) and each item.
      const step = event.key === "ArrowDown" ? 1 : -1;
      const positions = items.length + 1;
      active = ((active + 1 + step + positions) % positions) - 1;
      render();
    } else if (event.key === "Enter" && !list.hidden && active >= 0) {
      event.preventDefault();
      pick(active);
    } else if (event.key === "Escape" && !list.hidden) {
      event.preventDefault();
      close();
    }
  });
  // mousedown, not click: picking must happen before the input's blur closes the list.
  list.addEventListener("mousedown", event => {
    const option = event.target.closest("[data-index]");
    if (!option) return;
    event.preventDefault();
    pick(Number(option.dataset.index));
  });

  return { close };
}
