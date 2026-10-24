"use strict";

(() => {
  const dialog = document.querySelector("#exercise-demo-dialog");
  if (!dialog) return;
  const video = dialog.querySelector("video");
  const playbackError = dialog.querySelector(".exercise-demo-error");
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
      }).then((result) => result.demo).catch((error) => {
        cache.delete(name);
        throw error;
      });
      cache.set(name, result);
    }
    return cache.get(name);
  }

  async function fillHint(slot, name, isCurrent = () => true) {
    try {
      const demo = await lookup(name);
      if (!slot.isConnected || !isCurrent() || !demo) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "exercise-demo-button";
      button.textContent = "▷ Watch form";
      button.dataset.exerciseDemo = JSON.stringify(demo);
      button.setAttribute("aria-label", `Watch form for ${name}`);
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
    const button = event.target.closest("[data-exercise-demo]");
    if (!button) return;
    const demo = JSON.parse(button.dataset.exerciseDemo);
    dialog.querySelector("#exercise-demo-title").textContent = demo.name;
    video.setAttribute("aria-label", `${demo.name} form demonstration`);
    playbackError.classList.add("hidden");
    dialog.querySelector("[data-original-video]").href = demo.video_url;
    dialog.querySelector("[data-demo-source]").href = demo.source_url;
    dialog.querySelector("[data-demo-author]").textContent = demo.video_author;
    const license = dialog.querySelector("[data-demo-license]");
    license.textContent = demo.video_license.name;
    license.href = demo.video_license.url;
    video.src = demo.video_url;
    dialog.showModal();
  });
  dialog.querySelector("[data-close-demo]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => {
    video.pause();
    video.removeAttribute("src");
    video.load();
  });
  video.addEventListener("error", () => {
    if (video.hasAttribute("src")) playbackError.classList.remove("hidden");
  });
})();
