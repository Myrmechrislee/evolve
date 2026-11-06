"use strict";

(() => {
  const { tr, workoutText } = window.evolveI18n;
  const dialog = document.querySelector("#exercise-alternatives-dialog");
  if (!dialog) return;
  const equipment = dialog.querySelector("[data-alternatives-equipment]");
  const list = dialog.querySelector("[data-alternatives-list]");
  const status = dialog.querySelector("[data-alternatives-status]");
  const source = dialog.querySelector("[data-alternatives-source]");
  const retry = dialog.querySelector("[data-alternatives-retry]");
  let current = null;
  let controller = null;
  let version = 0;

  function canReplace() {
    return current?.input?.isConnected && !current.input.disabled && !current.input.readOnly
      && current.input.value.trim() === current.original;
  }

  function useExercise(exercise) {
    if (!canReplace()) return;
    const input = current.input;
    input.value = exercise.name;
    // Existing editor, translations, hints and autosave all observe these events.
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    dialog.close();
    input.focus();
  }

  function card(exercise) {
    const item = document.createElement("li");
    const name = document.createElement("h3");
    name.textContent = exercise.display_name || workoutText(exercise.name);
    const detail = document.createElement("p");
    detail.className = "exercise-hint-meta";
    detail.textContent = [
      tr("Equipment: {equipment}", { equipment: exercise.equipment ? tr(exercise.equipment) : tr("Unspecified equipment") }),
      tr("Targets: {muscles}", { muscles: exercise.primary_muscles.map((muscle) => tr(muscle)).join(", ") }),
      tr(exercise.level),
    ].join(" · ");
    const actions = document.createElement("div");
    actions.className = "exercise-alternative-actions";
    const form = document.createElement("button");
    form.type = "button";
    form.className = "exercise-hint-button";
    form.textContent = tr("View form");
    form.dataset.exerciseHintDetail = JSON.stringify(exercise);
    form.setAttribute("aria-label", tr("View form for {name}", { name: name.textContent }));
    form.setAttribute("aria-haspopup", "dialog");
    actions.append(form);
    if (canReplace()) {
      const use = document.createElement("button");
      use.type = "button";
      use.className = "button secondary small-button";
      use.textContent = tr("Use exercise");
      use.setAttribute("aria-label", tr("Use {name} instead", { name: name.textContent }));
      use.addEventListener("click", () => useExercise(exercise));
      actions.append(use);
    }
    item.append(name, detail, actions);
    return item;
  }

  async function load() {
    controller?.abort();
    controller = new AbortController();
    const requestVersion = ++version;
    const query = new URLSearchParams({ name: current.name, equipment: equipment.value });
    list.replaceChildren();
    list.setAttribute("aria-busy", "true");
    retry.hidden = true;
    status.textContent = tr("Finding alternative exercises…");
    try {
      const response = await fetch(`/api/exercises/alternatives?${query}`, {
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
      if (!response.ok) throw new Error("Alternatives unavailable");
      const result = await response.json();
      if (requestVersion !== version || !dialog.open) return;
      const selected = equipment.value;
      equipment.replaceChildren(new Option(tr("Any equipment"), ""), ...result.equipment.map((value) =>
        new Option(value === "unspecified" ? tr("Unspecified equipment") : tr(value), value)));
      equipment.value = selected;
      equipment.disabled = !result.equipment.length;
      list.replaceChildren(...result.exercises.map(card));
      status.textContent = result.exercises.length
        ? tr("{count} alternatives found.", { count: result.exercises.length })
        : tr("No alternatives found for this equipment. Try another option or enter a custom exercise.");
    } catch (error) {
      if (requestVersion !== version || error.name === "AbortError") return;
      status.textContent = tr("Alternative exercises could not load. Please try again.");
      retry.hidden = false;
    } finally {
      if (requestVersion === version) list.setAttribute("aria-busy", "false");
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-exercise-alternatives]");
    if (!button) return;
    const input = button.closest(".exercise-name-field")?.querySelector("[data-exercise-name]");
    current = { name: button.dataset.exerciseAlternatives, input, original: input?.value.trim() };
    source.textContent = tr("Alternatives for {name}", { name: workoutText(current.original || current.name) });
    equipment.replaceChildren(new Option(tr("Any equipment"), ""));
    equipment.disabled = true;
    dialog.showModal();
    load();
  });
  equipment.addEventListener("change", load);
  retry.addEventListener("click", load);
  dialog.querySelector("[data-close-alternatives]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right ||
        event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => {
    controller?.abort();
    version++;
    current = null;
    list.replaceChildren();
  });
})();
