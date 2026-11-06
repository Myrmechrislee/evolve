"use strict";

const { tr, workoutText } = window.evolveI18n;

const mobileNavigation = document.querySelector("#mobile-navigation");
const menuButtons = document.querySelectorAll("[data-menu]");
const phoneViewport = window.matchMedia("(max-width: 740px), (max-width: 960px) and (max-height: 500px) and (pointer: coarse)");
if (mobileNavigation) {
  let menuTrigger;
  menuButtons.forEach((button) => button.addEventListener("click", () => {
    menuTrigger = button;
    mobileNavigation.showModal();
    document.body.classList.add("navigation-open");
    menuButtons.forEach((trigger) => trigger.setAttribute("aria-expanded", "true"));
  }));
  mobileNavigation.querySelector("[data-close-navigation]").addEventListener("click", () => mobileNavigation.close());
  mobileNavigation.addEventListener("click", (event) => {
    const bounds = mobileNavigation.getBoundingClientRect();
    if (event.target === mobileNavigation && (event.clientY < bounds.top || event.clientY > bounds.bottom || event.clientX < bounds.left || event.clientX > bounds.right)) mobileNavigation.close();
  });
  mobileNavigation.addEventListener("close", () => {
    document.body.classList.remove("navigation-open");
    menuButtons.forEach((trigger) => trigger.setAttribute("aria-expanded", "false"));
    if (phoneViewport.matches) menuTrigger?.focus();
  });
  phoneViewport.addEventListener("change", () => {
    if (!phoneViewport.matches && mobileNavigation.open) mobileNavigation.close();
  });
}

const weekSelector = document.querySelector("[data-week-selector]");
if (weekSelector) {
  const buttons = [...weekSelector.querySelectorAll("[data-week-day]")];
  const days = [...document.querySelectorAll(".week-grid > .week-day")];
  let selectedDay = buttons.findIndex((button) => button.hasAttribute("aria-current"));
  if (selectedDay < 0) selectedDay = days.findIndex((day) => day.querySelector(".week-workout"));
  if (selectedDay < 0) selectedDay = 0;
  const showDay = () => {
    weekSelector.hidden = !phoneViewport.matches;
    days.forEach((day, index) => { day.hidden = phoneViewport.matches && index !== selectedDay; });
    buttons.forEach((button, index) => button.setAttribute("aria-pressed", String(index === selectedDay)));
  };
  buttons.forEach((button, index) => button.addEventListener("click", () => {
    selectedDay = index;
    showDay();
  }));
  phoneViewport.addEventListener("change", showDay);
  showDay();
}

// Keep the tab bar out of the way while the on-screen keyboard is open.
if (window.visualViewport) {
  const updateKeyboard = () => {
    const editing = document.activeElement?.matches("input, textarea, select, [contenteditable='true']");
    document.body.classList.toggle("keyboard-open", Boolean(editing && window.innerHeight - window.visualViewport.height > 150));
  };
  window.visualViewport.addEventListener("resize", updateKeyboard);
  document.addEventListener("focusin", updateKeyboard);
  document.addEventListener("focusout", () => requestAnimationFrame(updateKeyboard));
}
document.querySelectorAll("[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
const timezone = document.querySelector("[data-detect-timezone]");
if (timezone) timezone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
document.querySelectorAll('input[type="number"]').forEach((input) => {
  if (!input.hasAttribute("inputmode")) input.inputMode = input.step.includes(".") || input.step === "any" ? "decimal" : "numeric";
});

const workoutPicker = document.querySelector(".workout-picker");
workoutPicker?.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  if (event.target.closest("[data-workout-choice]")) workoutPicker.open = false;
});

const logForm = document.querySelector("[data-workout-form]");
if (logForm) {
  const list = document.querySelector("#log-exercises");
  const rowTemplate = document.querySelector("#log-exercise-template");
  const total = logForm.querySelector("[data-set-total]");
  const targets = new Map([...list.children].map((row) => [row.querySelector('[name="exercise_name"]').value, row.dataset]));
  let nextRowId = 0;
  const initializeRow = (row) => {
    const input = row.querySelector("[data-set-count]");
    input.id = `completed-sets-${++nextRowId}`;
    row.querySelector("[data-set-label]").htmlFor = input.id;
    row.querySelectorAll("[data-set-step]").forEach((button) => { button.hidden = false; });
  };
  const updateSetCounters = () => {
    let count = 0;
    list.querySelectorAll("[data-set-counter]").forEach((counter) => {
      const input = counter.querySelector("[data-set-count]");
      const value = input.valueAsNumber;
      const valid = Number.isInteger(value) && value >= 0 && value <= 30;
      if (valid) count += value;
      counter.querySelector('[data-set-step="-1"]').disabled = !Number.isFinite(value) || value <= 0;
      counter.querySelector('[data-set-step="1"]').disabled = value >= 30;
    });
    total.textContent = tr(count === 1 ? "{count} set completed" : "{count} sets completed", { count });
    total.hidden = false;
  };
  const addExercise = () => {
    if (list.children.length >= 20) return;
    const row = rowTemplate.content.firstElementChild.cloneNode(true);
    initializeRow(row);
    list.append(row);
    updateSetCounters();
    logForm.dispatchEvent(new Event("workout-draft-change"));
  };
  list.querySelectorAll(".log-exercise-row").forEach(initializeRow);
  if (!list.children.length) addExercise();
  updateSetCounters();
  document.querySelector("[data-add-log-exercise]").addEventListener("click", addExercise);
  list.addEventListener("input", (event) => {
    if (event.target.matches("[data-set-count]")) updateSetCounters();
  });
  list.addEventListener("click", (event) => {
    const stepButton = event.target.closest("[data-set-step]");
    if (stepButton) {
      const input = stepButton.closest("[data-set-counter]").querySelector("[data-set-count]");
      const current = Number.isFinite(input.valueAsNumber) ? Math.trunc(input.valueAsNumber) : 0;
      input.value = Math.max(0, Math.min(30, current + Number(stepButton.dataset.setStep)));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (event.target.closest("[data-remove-row]")) {
      event.target.closest(".log-exercise-row").remove();
      if (!list.children.length) addExercise();
      updateSetCounters();
      logForm.dispatchEvent(new Event("workout-draft-change"));
    }
  });
  logForm.addEventListener("restore-workout-draft", (event) => {
    const snapshot = event.detail;
    for (const name of ["title", "logged_date", "duration_minutes", "effort", "notes"]) {
      const input = logForm.elements.namedItem(name);
      if (input) input.value = snapshot.values[name];
    }
    logForm.elements.namedItem("request_id").value = snapshot.request_id;
    const rows = snapshot.exercises.map((exercise) => {
      const row = rowTemplate.content.firstElementChild.cloneNode(true);
      for (const [name, key] of Object.entries({ exercise_name: "name", exercise_sets: "sets", exercise_reps: "reps", exercise_weight: "weight_kg" })) {
        row.querySelector(`[name="${name}"]`).value = exercise[key];
      }
      const target = targets.get(exercise.name);
      if (target?.targetSets) {
        const hint = document.createElement("span");
        hint.className = "field-help set-target";
        hint.textContent = tr(target.targetSets === "1" ? "Target: {count} set" : "Target: {count} sets", { count: target.targetSets });
        row.querySelector(".exercise-set-field").append(hint);
        const repsHint = document.createElement("span");
        repsHint.className = "field-help";
        repsHint.textContent = tr("Target: {reps}", { reps: workoutText(target.targetReps) });
        row.querySelector('[name="exercise_reps"]').closest("label").append(repsHint);
      }
      initializeRow(row);
      return row;
    });
    list.replaceChildren(...rows);
    updateSetCounters();
  });
}
