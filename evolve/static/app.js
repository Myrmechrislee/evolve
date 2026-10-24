"use strict";

document.querySelector("[data-menu]")?.addEventListener("click", (event) => {
  const button = event.currentTarget;
  const open = document.querySelector("#sidebar").classList.toggle("open");
  button.setAttribute("aria-expanded", String(open));
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    document.querySelector("#sidebar")?.classList.remove("open");
    document.querySelector("[data-menu]")?.setAttribute("aria-expanded", "false");
  }
});
document.querySelectorAll("[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
const timezone = document.querySelector("[data-detect-timezone]");
if (timezone) timezone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

const logForm = document.querySelector("[data-workout-form]");
if (logForm) {
  const list = document.querySelector("#log-exercises");
  const addExercise = () => {
    if (list.children.length >= 20) return;
    const row = document.createElement("div");
    row.className = "log-exercise-row";
    row.innerHTML = `<div class="exercise-name-field"><label>Exercise<input name="exercise_name" data-exercise-name required maxlength="100" placeholder="Exercise name"></label><div data-exercise-hint hidden></div></div>
      <label>Sets<input type="number" name="exercise_sets" value="3" min="1" max="30" required></label>
      <label>Reps / set<input type="number" name="exercise_reps" value="10" min="0" max="500" required></label>
      <label>kg / rep<input type="number" name="exercise_weight" value="0" min="0" max="1000" step="0.1" required></label>
      <button type="button" class="icon-button remove-row" data-remove-row aria-label="Remove exercise">×</button>`;
    list.append(row);
  };
  if (!list.children.length) addExercise();
  document.querySelector("[data-add-log-exercise]").addEventListener("click", addExercise);
  list.addEventListener("click", (event) => {
    if (event.target.closest("[data-remove-row]")) {
      event.target.closest(".log-exercise-row").remove();
      if (!list.children.length) addExercise();
    }
  });
}
