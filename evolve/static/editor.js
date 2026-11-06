"use strict";

(() => {
  const { tr } = window.evolveI18n;
  const form = document.querySelector("[data-plan-editor]");
  if (!form) return;
  const initial = JSON.parse(document.querySelector("#plan-data").textContent);
  const list = document.querySelector("#session-list");
  const errorBox = document.querySelector("#editor-error");
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const trackingCache = new Map();
  const showError = (message) => {
    errorBox.textContent = tr(message);
    errorBox.classList.remove("hidden");
    errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  function addExercise(container, exercise = {}) {
    if (container.children.length >= 15) return showError("A session can contain up to 15 exercises.");
    const row = document.createElement("div");
    row.className = "editor-exercise";
    row.dataset.id = exercise.id || "";
    row.innerHTML = `<div class="exercise-name exercise-name-field"><label>${tr("Exercise")}<input data-field="name" data-exercise-name required maxlength="100" placeholder="${tr("e.g. Goblet squat")}"></label><div data-exercise-hint hidden></div></div>
      <label>${tr("Sets")}<input data-field="sets" type="number" inputmode="numeric" min="1" max="20" required></label>
      <label>${tr("Reps / time")}<input data-field="reps" required maxlength="40" placeholder="8–12"></label>
      <label>${tr("Rest (s)")}<input data-field="rest_seconds" type="number" inputmode="numeric" min="0" max="600" required></label>
      <button type="button" class="icon-button remove-row" data-remove-exercise aria-label="${tr("Remove exercise")}">×</button>
      <label class="exercise-notes">${tr("Notes")}<span class="optional">${tr("Optional")}</span><input data-field="notes" maxlength="500" placeholder="${tr("Form cues, warm-up, progression, or substitutions…")}"></label>
      <details class="exercise-notes exercise-tracking-adjustments" data-tracking-adjustments>
        <summary data-tracking-summary>${tr("Adjust tracking")}</summary>
        <p class="field-help" data-custom-tracking-help hidden>${tr("This exercise is not in the library. Choose its load type and tracking method.")}</p>
        <input type="hidden" data-field="tracking_override" value="0">
        <div class="form-grid">
        <label>${tr("Load type")}<select data-field="load_type"><option value="">${tr("Automatic")}</option><option value="weighted">${tr("External weight")}</option><option value="bodyweight">${tr("Bodyweight")}</option></select></label>
        <label>${tr("Track")}<select data-field="measurement"><option value="">${tr("Automatic")}</option><option value="reps">${tr("Reps")}</option><option value="time">${tr("Time")}</option></select></label>
        <label data-bodyweight-field hidden>${tr("Bodyweight used (%)")}<input data-field="bodyweight_percent" type="number" inputmode="decimal" min="1" max="100" step="0.1"><span class="field-help">${tr("Percentages are exercise-specific tracking estimates.")}</span></label>
        </div>
        <button type="button" class="text-button" data-reset-tracking hidden>${tr("Use library defaults")}</button>
      </details>`;
    const defaults = { name: "", sets: 3, reps: "10", rest_seconds: 90, notes: "", load_type: "", measurement: "", bodyweight_percent: 100 };
    Object.keys(defaults).forEach((key) => {
      row.querySelector(`[data-field="${key}"]`).value = exercise[key] ?? defaults[key];
    });
    const manual = exercise.tracking_override ?? Boolean(exercise.load_type || exercise.measurement || exercise.bodyweight_percent);
    row.querySelector('[data-field="tracking_override"]').value = manual ? "1" : "0";
    container.append(row);
    const nameInput = row.querySelector('[data-field="name"]');
    const field = (key) => row.querySelector(`[data-field="${key}"]`);
    const trackingKeys = ["load_type", "measurement", "bodyweight_percent"];
    const edited = new Set(manual ? trackingKeys : []);
    let previousName = nameInput.value.trim(), version = 0, timer;
    const renderTracking = () => {
      const bodyweight = field("load_type").value === "bodyweight";
      row.querySelector("[data-bodyweight-field]").hidden = !bodyweight;
      field("bodyweight_percent").required = bodyweight;
      field("bodyweight_percent").type = bodyweight ? "number" : "hidden";
    };
    const infer = () => {
      clearTimeout(timer);
      const name = nameInput.value.trim();
      if (name !== previousName) {
        edited.clear();
        field("tracking_override").value = "0";
        previousName = name;
        row.querySelector("[data-tracking-adjustments]").open = false;
      }
      const current = ++version;
      if (!name || name.length > 100) return;
      timer = setTimeout(async () => {
        try {
          const query = new URLSearchParams({ name, target: field("reps").value });
          const url = `/api/exercises/tracking?${query}`;
          if (!trackingCache.has(url)) trackingCache.set(url, fetch(url, { headers: { Accept: "application/json" } })
            .then(response => { if (!response.ok) throw new Error("Tracking unavailable"); return response.json(); })
            .catch(error => { trackingCache.delete(url); throw error; }));
          const metadata = await trackingCache.get(url);
          if (version !== current || !row.isConnected) return;
          trackingKeys.forEach(key => { if (!edited.has(key)) field(key).value = metadata[key]; });
          field("tracking_override").value = edited.size || !metadata.known ? "1" : "0";
          row.querySelector("[data-tracking-summary]").textContent = tr(metadata.known ? "Adjust tracking" : "Set up custom exercise");
          row.querySelector("[data-custom-tracking-help]").hidden = metadata.known;
          row.querySelector("[data-reset-tracking]").hidden = !metadata.known;
          if (!metadata.known || !edited.size) row.querySelector("[data-tracking-adjustments]").open = !metadata.known;
          renderTracking();
        } catch { /* Saved settings and manual adjustments still work offline. */ }
      }, 180);
    };
    row.addEventListener("input", (event) => {
      const key = event.target.dataset.field;
      if (key === "name" || key === "reps") { if (!event.isComposing) infer(); }
      else if (trackingKeys.includes(key)) {
        edited.add(key);
        field("tracking_override").value = "1";
        renderTracking();
      }
    });
    nameInput.addEventListener("compositionend", infer);
    row.querySelector("[data-reset-tracking]").addEventListener("click", () => {
      edited.clear(); field("tracking_override").value = "0"; infer();
    });
    renderTracking();
    infer();
  }
  function addSession(item = {}) {
    if (list.children.length >= 7) return showError("A plan can contain up to 7 weekly sessions.");
    const card = document.createElement("section");
    card.className = "card session-editor";
    card.dataset.id = item.id || "";
    card.innerHTML = `<div class="session-editor-heading">
      <label>${tr("Session name")}<input data-session-title required maxlength="100" placeholder="${tr("e.g. Upper body strength")}"></label>
      <label class="session-day">${tr("Weekday")}<select data-session-day></select></label>
      <button type="button" class="icon-button" data-remove-session aria-label="${tr("Remove session")}">×</button>
      </div><div class="editor-exercises"></div><button type="button" class="text-button text-link editor-add-exercise" data-add-exercise>${tr("＋ Add exercise")}</button>`;
    card.querySelector("[data-session-title]").value = item.title || "";
    const select = card.querySelector("[data-session-day]");
    const used = [...list.querySelectorAll("[data-session-day]")].map((el) => el.value);
    days.forEach((day) => select.add(new Option(tr(day), day)));
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
            if (["load_type", "measurement"].includes(input.dataset.field) && !input.value) return;
            exercise[input.dataset.field] = input.dataset.field === "tracking_override" ? input.value === "1"
              : input.type === "number" || input.dataset.field === "bodyweight_percent" ? Number(input.value) : input.value.trim();
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
  form.addEventListener("invalid", (event) => {
    const adjustments = event.target.closest("[data-tracking-adjustments]");
    if (adjustments) adjustments.open = true;
  }, true);
})();
