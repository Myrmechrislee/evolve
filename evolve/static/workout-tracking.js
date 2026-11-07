"use strict";

(() => {
  const form = document.querySelector("[data-workout-form]");
  if (!form) return;
  const { tr } = window.evolveI18n;
  const list = form.querySelector("#log-exercises");
  const states = new WeakMap();
  const field = (row, name) => row.querySelector(`[name="exercise_${name}"]`);

  function render(row) {
    const bodyweight = field(row, "load_type").value === "bodyweight";
    const timed = field(row, "measurement").value === "time";
    for (const [selector, name, active] of [
      ["[data-weight-field]", "weight", !bodyweight],
      ["[data-bodyweight-field]", "bodyweight_percent", bodyweight],
      ["[data-reps-field]", "reps", !timed],
      ["[data-time-field]", "duration_seconds", timed],
    ]) {
      row.querySelector(selector).hidden = !active;
      // Hidden controls stay in the form so each row retains aligned columns.
      const input = field(row, name);
      input.required = active;
      input.type = active ? "number" : "hidden";
    }
    const percent = Number(field(row, "bodyweight_percent").value);
    const weight = Number(form.dataset.bodyweight);
    const output = row.querySelector("[data-effective-load]");
    output.textContent = bodyweight && percent >= 1 && percent <= 100 && weight > 0
      ? tr("{weight} kg × {percent}% = {load} kg effective load", {
        weight, percent, load: Number((weight * percent / 100).toFixed(3)),
      }) : "";
    const known = row.dataset.libraryKnown === "true";
    row.querySelector("[data-tracking-summary]").textContent = tr(known || !field(row, "name").value.trim()
      ? "Adjust tracking" : "Set up custom exercise");
    row.querySelector("[data-custom-tracking-help]").hidden = known || !field(row, "name").value.trim();
    row.querySelector("[data-reset-tracking]").hidden = !known;
  }

  function infer(row) {
    const state = states.get(row);
    clearTimeout(state.timer);
    state.controller?.abort();
    const version = ++state.version;
    const name = field(row, "name").value.trim();
    if (name !== state.name) {
      state.edited.clear();
      state.name = name;
      field(row, "tracking_override").value = "0";
      field(row, "muscle_group").value = "";
      row.querySelector("[data-tracking-adjustments]").open = false;
    }
    if (!name || name.length > 100) return;
    state.timer = setTimeout(async () => {
      try {
        state.controller = new AbortController();
        const target = name === state.initialName ? row.dataset.targetReps || "" : "";
        const response = await fetch(`/api/exercises/tracking?${new URLSearchParams({ name, target })}`, {
          headers: { Accept: "application/json" }, signal: state.controller.signal,
        });
        if (!response.ok) return;
        const defaults = await response.json();
        if (state.version !== version || !row.isConnected || field(row, "name").value.trim() !== name) return;
        for (const key of ["load_type", "measurement", "bodyweight_percent"]) {
          if (!state.edited.has(`exercise_${key}`)) field(row, key).value = defaults[key];
        }
        row.dataset.libraryKnown = String(defaults.known);
        field(row, "tracking_override").value = state.edited.size || !defaults.known ? "1" : "0";
        if (!defaults.known || !state.edited.size) row.querySelector("[data-tracking-adjustments]").open = !defaults.known;
        render(row);
        form.dispatchEvent(new Event("workout-draft-change"));
      } catch { /* Manual tracking choices remain available offline. */ }
    }, 180);
  }

  function initialize(row) {
    if (states.has(row)) return;
    const name = field(row, "name").value.trim();
    const edited = new Set(field(row, "tracking_override").value === "1"
      ? ["exercise_load_type", "exercise_measurement", "exercise_bodyweight_percent"] : []);
    states.set(row, { version: 0, edited, name, initialName: name });
    render(row);
    if (row.dataset.inferTracking || name && row.dataset.libraryKnown !== "true") infer(row);
  }
  [...list.children].forEach(initialize);
  new MutationObserver(() => [...list.children].forEach(initialize)).observe(list, { childList: true });
  list.addEventListener("input", (event) => {
    const row = event.target.closest(".log-exercise-row");
    if (!row) return;
    initialize(row);
    if (event.target.name === "exercise_name") {
      if (!event.isComposing) infer(row);
    } else {
      // Preserve each explicit choice while filling other automatic defaults.
      if (["exercise_load_type", "exercise_measurement", "exercise_bodyweight_percent"].includes(event.target.name)) {
        states.get(row).edited.add(event.target.name);
        field(row, "tracking_override").value = "1";
      }
      render(row);
    }
  });
  list.addEventListener("compositionend", (event) => {
    const row = event.target.closest(".log-exercise-row");
    if (row && event.target.name === "exercise_name") infer(row);
  });
  list.addEventListener("change", (event) => {
    const row = event.target.closest(".log-exercise-row");
    if (!row) return;
    initialize(row);
    if (event.target.name !== "exercise_name") {
      if (["exercise_load_type", "exercise_measurement", "exercise_bodyweight_percent"].includes(event.target.name)) {
        states.get(row).edited.add(event.target.name);
        field(row, "tracking_override").value = "1";
      }
      render(row);
    }
  });
  list.addEventListener("click", (event) => {
    if (!event.target.closest("[data-reset-tracking]")) return;
    const row = event.target.closest(".log-exercise-row");
    states.get(row).edited.clear();
    field(row, "tracking_override").value = "0";
    field(row, "muscle_group").value = "";
    infer(row);
  });
  form.addEventListener("invalid", (event) => {
    const adjustments = event.target.closest("[data-tracking-adjustments]");
    if (adjustments) adjustments.open = true;
  }, true);
})();
