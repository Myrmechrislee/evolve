"use strict";

(() => {
  const main = document.querySelector("#main");
  if (!main) return;
  const fields = new WeakMap();
  const cache = new Map();
  let sequence = 0;
  let current = null;

  function position(state, revealInput = false) {
    const viewport = window.visualViewport;
    const top = viewport?.offsetTop || 0;
    let bottom = top + (viewport?.height || window.innerHeight);
    const footer = main.querySelector(".sticky-footer")?.getBoundingClientRect();
    if (footer && footer.top > top && footer.top < bottom) bottom = footer.top - 8;
    const inputBounds = state.input.getBoundingClientRect();
    if (revealInput && (inputBounds.top < top + 12 || inputBounds.bottom > bottom - 12)) {
      state.input.scrollIntoView({ block: "center" });
    }
    const bounds = state.wrapper.getBoundingClientRect();
    const above = bounds.top - top - 12;
    const below = bottom - bounds.bottom - 12;
    const opensAbove = below < 180 && above > below;
    state.list.classList.toggle("exercise-suggestions-above", opensAbove);
    state.list.style.maxHeight = `${Math.min(280, Math.max(72, opensAbove ? above : below))}px`;
  }

  function close(state) {
    clearTimeout(state.timer);
    state.controller?.abort();
    state.version++;
    state.list.hidden = true;
    state.status.hidden = true;
    state.input.setAttribute("aria-expanded", "false");
    state.input.removeAttribute("aria-activedescendant");
    state.active = -1;
    if (current === state) current = null;
  }

  function highlight(state, index) {
    state.active = index;
    [...state.list.children].forEach((option, position) => {
      option.setAttribute("aria-selected", String(position === index));
    });
    const option = state.list.children[index];
    if (option) {
      state.input.setAttribute("aria-activedescendant", option.id);
      option.scrollIntoView({ block: "nearest" });
    } else state.input.removeAttribute("aria-activedescendant");
  }

  function choose(state, index) {
    const exercise = state.items[index];
    if (!exercise) return;
    state.input.value = exercise.name;
    state.input.focus();
    state.input.dispatchEvent(new Event("input", { bubbles: true }));
    state.input.dispatchEvent(new Event("change", { bubbles: true }));
    close(state);
  }

  async function suggest(state, query, version) {
    try {
      let items = cache.get(query.toLocaleLowerCase());
      if (!items) {
        state.controller = new AbortController();
        const response = await fetch(`/api/exercises/search?${new URLSearchParams({ q: query })}`, {
          headers: { Accept: "application/json" }, signal: state.controller.signal,
        });
        if (!response.ok) throw new Error("Exercise search unavailable");
        items = (await response.json()).exercises;
        if (cache.size >= 100) cache.delete(cache.keys().next().value);
        cache.set(query.toLocaleLowerCase(), items);
      }
      if (state.version !== version || !state.input.isConnected || document.activeElement !== state.input) return;
      state.items = items;
      state.list.replaceChildren(...items.map((exercise, index) => {
        const option = document.createElement("span");
        option.className = "exercise-suggestion";
        option.id = `${state.list.id}-${index}`;
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        const name = document.createElement("span");
        name.className = "exercise-suggestion-name";
        name.textContent = exercise.name;
        const detail = document.createElement("span");
        detail.className = "exercise-suggestion-detail";
        detail.textContent = [exercise.equipment, ...exercise.primary_muscles].filter(Boolean).join(" · ");
        option.append(name, detail);
        option.addEventListener("mousedown", (event) => event.preventDefault());
        option.addEventListener("click", () => choose(state, index));
        return option;
      }));
      if (items.length) position(state, true);
      state.list.hidden = !items.length;
      state.input.setAttribute("aria-expanded", String(Boolean(items.length)));
      state.status.textContent = items.length
        ? `${items.length} exercise suggestions available. Use the up and down arrow keys to choose.`
        : "No matching exercises.";
      state.status.classList.toggle("sr-only", Boolean(items.length));
      state.status.hidden = false;
    } catch (error) {
      if (error.name !== "AbortError" && state.version === version) close(state);
    }
  }

  function schedule(state, delay = 180) {
    if (current && current !== state) close(current);
    close(state);
    const query = state.input.value.trim();
    if (query.length < 2 || query.length > 100 || state.composing) return;
    current = state;
    const version = state.version;
    state.timer = setTimeout(() => suggest(state, query, version), delay);
  }

  function initialize(input) {
    if (fields.has(input)) return;
    const wrapper = document.createElement("span");
    wrapper.className = "exercise-autocomplete";
    const label = input.closest("label");
    label.before(wrapper);
    const list = document.createElement("span");
    list.id = `exercise-suggestions-${++sequence}`;
    list.className = "exercise-suggestions";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", "Exercise suggestions");
    list.hidden = true;
    const status = document.createElement("span");
    status.className = "exercise-search-status";
    status.setAttribute("role", "status");
    status.hidden = true;
    wrapper.append(label, list, status);
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-haspopup", "listbox");
    input.setAttribute("aria-controls", list.id);
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("autocomplete", "off");
    const state = { input, wrapper, list, status, items: [], active: -1, version: 0 };
    fields.set(input, state);
    input.addEventListener("focus", () => schedule(state));
    input.addEventListener("input", () => schedule(state));
    input.addEventListener("compositionstart", () => { state.composing = true; close(state); });
    input.addEventListener("compositionend", () => { state.composing = false; schedule(state); });
    input.addEventListener("blur", () => close(state));
    input.addEventListener("keydown", (event) => {
      if (event.isComposing) return;
      if (event.key === "Escape" && current === state) {
        event.preventDefault();
        close(state);
      } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        if (list.hidden) { schedule(state, 0); return; }
        const next = event.key === "ArrowDown" ? state.active + 1 : state.active < 0 ? state.items.length - 1 : state.active - 1;
        highlight(state, (next + state.items.length) % state.items.length);
      } else if (event.key === "Enter" && !list.hidden && state.active >= 0) {
        event.preventDefault();
        choose(state, state.active);
      } else if (event.key === "Tab") close(state);
    });
  }

  function scan(root) {
    if (root.matches?.("[data-exercise-name]")) initialize(root);
    root.querySelectorAll("[data-exercise-name]").forEach(initialize);
  }
  new MutationObserver((mutations) => {
    if (current && !current.input.isConnected) close(current);
    mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    }));
  }).observe(main, { childList: true, subtree: true });
  scan(main);
  const reposition = () => { if (current && !current.list.hidden) position(current); };
  window.addEventListener("resize", reposition);
  window.visualViewport?.addEventListener("resize", reposition);
  window.addEventListener("scroll", reposition, true);
})();
