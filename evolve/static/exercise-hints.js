"use strict";

(() => {
  const dialog = document.querySelector("#exercise-hint-dialog");
  if (!dialog) return;
  const images = dialog.querySelector("[data-hint-images]");
  const imageError = dialog.querySelector(".exercise-hint-error");
  const cache = new Map();
  const initialized = new WeakSet();
  const timers = new WeakMap();
  const names = new WeakMap();

  function lookup(name) {
    if (!cache.has(name)) {
      if (cache.size >= 200) cache.delete(cache.keys().next().value);
      const result = fetch(`/api/exercises/hint?${new URLSearchParams({ name })}`, {
        headers: { Accept: "application/json" },
      }).then((response) => {
        if (!response.ok) throw new Error("Exercise hint unavailable");
        return response.json();
      }).then((result) => result.hint).catch((error) => {
        cache.delete(name);
        throw error;
      });
      cache.set(name, result);
    }
    return cache.get(name);
  }

  async function fillHint(slot, name, isCurrent = () => true) {
    try {
      const hint = await lookup(name);
      if (!slot.isConnected || !isCurrent() || !hint) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "exercise-hint-button";
      button.textContent = "View form";
      button.dataset.exerciseHintDetail = JSON.stringify(hint);
      button.setAttribute("aria-label", `View form for ${name}`);
      button.setAttribute("aria-haspopup", "dialog");
      slot.replaceChildren(button);
      slot.hidden = false;
    } catch {
      // A hint must never interrupt editing or saving a workout.
    }
  }

  function scheduleHint(input, delay = 300) {
    const name = input.value.trim();
    // Blurring an edited field emits change before a nearby button's click.
    // Keep the existing hint in place when the name itself has not changed.
    if (names.get(input) === name) return;
    names.set(input, name);
    clearTimeout(timers.get(input));
    const slot = input.closest(".exercise-name-field").querySelector("[data-exercise-hint]");
    slot.replaceChildren();
    slot.hidden = true;
    if (!name || name.length > 100) return;
    timers.set(input, setTimeout(() => {
      if (input.isConnected) fillHint(slot, name, () => input.value.trim() === name);
    }, delay));
  }

  function scan(root) {
    const nodes = [];
    if (root.matches?.("[data-exercise-name], [data-exercise-hint-name]")) nodes.push(root);
    nodes.push(...root.querySelectorAll("[data-exercise-name], [data-exercise-hint-name]"));
    nodes.forEach((node) => {
      if (initialized.has(node)) return;
      initialized.add(node);
      if (node.matches("[data-exercise-name]")) scheduleHint(node, 0);
      else if (node.dataset.exerciseHintName) fillHint(node, node.dataset.exerciseHintName);
    });
  }

  document.addEventListener("input", (event) => {
    if (event.target.matches("[data-exercise-name]")) scheduleHint(event.target);
  });
  document.addEventListener("change", (event) => {
    if (event.target.matches("[data-exercise-name]")) scheduleHint(event.target);
  });
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    }));
  });
  observer.observe(document.querySelector("#main"), { childList: true, subtree: true });
  scan(document.querySelector("#main"));

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-exercise-hint-detail]");
    if (!button) return;
    const hint = JSON.parse(button.dataset.exerciseHintDetail);
    dialog.querySelector("#exercise-hint-title").textContent = hint.name;
    dialog.querySelector("[data-hint-meta]").textContent = [
      hint.primary_muscles.length ? `Targets: ${hint.primary_muscles.join(", ")}` : "",
      hint.equipment ? `Equipment: ${hint.equipment}` : "",
    ].filter(Boolean).join(" · ");
    imageError.classList.add("hidden");
    dialog.querySelector("[data-hint-source]").href = hint.source_url;
    dialog.querySelector("[data-hint-instructions]").replaceChildren(...hint.instructions.map((step) => {
      const item = document.createElement("li");
      item.textContent = step;
      return item;
    }));
    images.replaceChildren(...hint.images.map((url, index) => {
      const figure = document.createElement("figure");
      const photo = document.createElement("img");
      photo.alt = `${hint.name}, form photo ${index + 1}`;
      photo.decoding = "async";
      photo.addEventListener("error", () => {
        if (!photo.isConnected) return;
        figure.hidden = true;
        imageError.classList.remove("hidden");
      });
      photo.src = url;
      const caption = document.createElement("figcaption");
      caption.textContent = `Position ${index + 1}`;
      figure.append(photo, caption);
      return figure;
    }));
    dialog.showModal();
  });
  dialog.querySelector("[data-close-hint]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => {
    images.replaceChildren();
  });
})();
