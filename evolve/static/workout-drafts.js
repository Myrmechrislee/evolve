"use strict";

(() => {
  const draftKey = (owner, occurrence) => `evolve:workout-draft:v1:${owner}:${occurrence || "freestyle"}`;
  const readLocal = (key) => {
    try { return JSON.parse(localStorage.getItem(key)); } catch { return null; }
  };
  const clearLocal = (key, requestId) => {
    try {
      if (readLocal(key)?.request_id === requestId) localStorage.removeItem(key);
    } catch { /* Server drafts still work when browser storage is unavailable. */ }
  };
  document.querySelectorAll("[data-completed-workout-draft]").forEach((marker) => {
    clearLocal(draftKey(marker.dataset.draftOwner, marker.dataset.occurrence), marker.dataset.requestId);
  });

  const form = document.querySelector("[data-workout-form]");
  if (!form) return;
  const list = form.querySelector("#log-exercises");
  const status = form.querySelector("[data-workout-draft-status]");
  const occurrence = form.elements.namedItem("occurrence").value;
  const key = draftKey(form.dataset.draftOwner, occurrence);
  const fields = { title: 100, logged_date: 10, duration_minutes: 32, effort: 32, notes: 3000 };
  const exerciseFields = { name: 100, sets: 32, reps: 32, weight_kg: 32 };
  let latest = null;
  let dirty = false;
  let inFlight = false;
  let submitting = false;
  let finished = false;
  let timer;
  let failures = 0;
  let locallySaved = false;

  const showStatus = (message, state = "") => {
    status.textContent = message;
    status.dataset.state = state;
    status.hidden = false;
  };
  const storeLocal = (snapshot) => {
    try {
      localStorage.setItem(key, JSON.stringify(snapshot));
      locallySaved = true;
    } catch { locallySaved = false; }
  };
  const capture = () => ({
    schema: 1,
    request_id: form.elements.namedItem("request_id").value,
    occurrence,
    updated_at: new Date().toISOString(),
    pending: true,
    values: Object.fromEntries(Object.keys(fields).map((name) => [name, form.elements.namedItem(name)?.value || ""])),
    exercises: [...list.children].map((row) => ({
      name: row.querySelector('[name="exercise_name"]').value,
      sets: row.querySelector('[name="exercise_sets"]').value,
      reps: row.querySelector('[name="exercise_reps"]').value,
      weight_kg: row.querySelector('[name="exercise_weight"]').value,
    })),
  });
  const validStrings = (record, limits) => record && typeof record === "object" && !Array.isArray(record)
    && Object.entries(limits).every(([name, limit]) => typeof record[name] === "string" && record[name].length <= limit);
  const validSnapshot = (snapshot) => snapshot?.schema === 1 && snapshot.occurrence === occurrence
    && typeof snapshot.request_id === "string" && /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(snapshot.request_id)
    && validStrings(snapshot.values, fields) && Array.isArray(snapshot.exercises)
    && snapshot.exercises.length >= 1 && snapshot.exercises.length <= 20
    && snapshot.exercises.every((row) => validStrings(row, exerciseFields));

  const save = async () => {
    clearTimeout(timer);
    if (!dirty || inFlight || submitting || finished) return;
    const snapshot = latest;
    dirty = false;
    inFlight = true;
    let succeeded = false;
    try {
      if (!navigator.onLine) throw new Error("Offline");
      const response = await fetch(form.dataset.draftUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content },
        body: JSON.stringify(snapshot),
        keepalive: true,
      });
      if (!response.ok) throw new Error("Draft save failed");
      const result = await response.json();
      if (result.completed) {
        finished = true;
        dirty = false;
        clearLocal(key, snapshot.request_id);
        showStatus("This workout has already been saved.");
        return;
      }
      if (!result.saved) throw new Error("Draft save failed");
      succeeded = true;
      failures = 0;
      if (latest === snapshot && !submitting) {
        latest = { ...snapshot, pending: false };
        storeLocal(latest);
        showStatus("Draft saved · finish with Save workout", "saved");
      }
    } catch {
      dirty = true;
      failures++;
      if (!submitting) showStatus(locallySaved
        ? "Draft saved on this device · waiting to sync"
        : "Draft not saved yet · retrying", "pending");
    } finally {
      inFlight = false;
      if (dirty && !submitting && !finished && navigator.onLine) {
        timer = setTimeout(save, succeeded ? 0 : Math.min(30000, 1500 * 2 ** Math.min(failures, 4)));
      }
    }
  };
  const changed = () => {
    if (submitting || finished) return;
    latest = capture();
    dirty = true;
    storeLocal(latest);
    showStatus(navigator.onLine ? "Saving draft…" : locallySaved
      ? "Draft saved on this device · waiting to sync" : "Draft not saved yet · offline", "pending");
    clearTimeout(timer);
    timer = setTimeout(save, 400);
  };

  const local = readLocal(key);
  if (!form.hasAttribute("data-draft-submitted") && validSnapshot(local) && local.pending
      && Date.parse(local.updated_at) > (Date.parse(form.dataset.draftUpdated) || 0)) {
    form.dispatchEvent(new CustomEvent("restore-workout-draft", { detail: local }));
    changed();
  } else if (form.hasAttribute("data-draft-submitted")) {
    changed();
  } else {
    showStatus(form.hasAttribute("data-draft-restored")
      ? "Draft restored · autosaves as you type" : "Autosaves as you type · finish with Save workout");
  }

  form.addEventListener("input", changed);
  form.addEventListener("change", changed);
  form.addEventListener("workout-draft-change", changed);
  form.addEventListener("submit", () => {
    changed();
    submitting = true;
    dirty = false;
    clearTimeout(timer);
  });
  window.addEventListener("online", () => { if (dirty) save(); });
  window.addEventListener("pagehide", () => { if (dirty) save(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden && dirty) save(); });
})();
