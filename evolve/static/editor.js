"use strict";

(() => {
  const form = document.querySelector("[data-plan-editor]");
  if (!form) return;
  const initial = JSON.parse(document.querySelector("#plan-data").textContent);
  const list = document.querySelector("#session-list");
  const errorBox = document.querySelector("#editor-error");
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  function addExercise(container, exercise = {}) {
    if (container.children.length >= 15) return showError("A session can contain up to 15 exercises.");
    const row = document.createElement("div");
    row.className = "editor-exercise";
    row.dataset.id = exercise.id || "";
    row.innerHTML = `<div class="exercise-name exercise-name-field"><label>Exercise<input data-field="name" data-exercise-name required maxlength="100" placeholder="e.g. Goblet squat"></label><div data-exercise-hint hidden></div></div>
      <label>Sets<input data-field="sets" type="number" min="1" max="20" required></label>
      <label>Reps / time<input data-field="reps" required maxlength="40" placeholder="8–12"></label>
      <label>Rest (s)<input data-field="rest_seconds" type="number" min="0" max="600" required></label>
      <button type="button" class="icon-button remove-row" data-remove-exercise aria-label="Remove exercise">×</button>
      <label class="exercise-notes">Notes <span class="optional">Optional</span><input data-field="notes" maxlength="500" placeholder="Form cues, warm-up, progression, or substitutions…"></label>`;
    const defaults = { name: "", sets: 3, reps: "10", rest_seconds: 90, notes: "" };
    Object.keys(defaults).forEach((key) => {
      row.querySelector(`[data-field="${key}"]`).value = exercise[key] ?? defaults[key];
    });
    container.append(row);
  }
  function addSession(item = {}) {
    if (list.children.length >= 7) return showError("A plan can contain up to 7 weekly sessions.");
    const card = document.createElement("section");
    card.className = "card session-editor";
    card.dataset.id = item.id || "";
    card.innerHTML = `<div class="session-editor-heading">
      <label>Session name<input data-session-title required maxlength="100" placeholder="e.g. Upper body strength"></label>
      <label class="session-day">Weekday<select data-session-day></select></label>
      <button type="button" class="icon-button" data-remove-session aria-label="Remove session">×</button>
      </div><div class="editor-exercises"></div><button type="button" class="text-button text-link editor-add-exercise" data-add-exercise>＋ Add exercise</button>`;
    card.querySelector("[data-session-title]").value = item.title || "";
    const select = card.querySelector("[data-session-day]");
    const used = [...list.querySelectorAll("[data-session-day]")].map((el) => el.value);
    days.forEach((day) => select.add(new Option(day, day)));
    select.value = item.day || days.find((day) => !used.includes(day)) || "Mon";
    const exercises = Array.isArray(item.exercises) && item.exercises.length ? item.exercises : [{}];
    exercises.forEach((exercise) => addExercise(card.querySelector(".editor-exercises"), exercise));
    list.append(card);
  }
  document.querySelector("[data-add-session]").addEventListener("click", () => addSession());
  list.addEventListener("click", (event) => {
    const card = event.target.closest(".session-editor");
    if (!card) return;
    if (event.target.closest("[data-add-exercise]")) addExercise(card.querySelector(".editor-exercises"));
    if (event.target.closest("[data-remove-exercise]")) {
      event.target.closest(".editor-exercise").remove();
      if (!card.querySelector(".editor-exercises").children.length) addExercise(card.querySelector(".editor-exercises"));
    }
    if (event.target.closest("[data-remove-session]")) {
      card.remove();
      if (!list.children.length) addSession();
    }
  });
  const sessions = Array.isArray(initial.sessions) && initial.sessions.length ? initial.sessions : [{}];
  sessions.forEach(addSession);
  form.addEventListener("submit", (event) => {
    const payload = {
      name: form.elements.plan_name.value.trim(), goal: form.elements.plan_goal.value.trim(),
      weeks: Number(form.elements.plan_weeks.value),
      sessions: [...list.children].map((card) => ({
        id: card.dataset.id, title: card.querySelector("[data-session-title]").value.trim(),
        day: card.querySelector("[data-session-day]").value,
        exercises: [...card.querySelectorAll(".editor-exercise")].map((row) => {
          const exercise = { id: row.dataset.id };
          row.querySelectorAll("[data-field]").forEach((input) => {
            exercise[input.dataset.field] = input.type === "number" ? Number(input.value) : input.value.trim();
          });
          return exercise;
        }),
      })),
    };
    if (new Set(payload.sessions.map((session) => session.day)).size !== payload.sessions.length) {
      event.preventDefault();
      return showError("Choose a different weekday for each session.");
    }
    form.elements.plan_payload.value = JSON.stringify(payload);
  });
})();
