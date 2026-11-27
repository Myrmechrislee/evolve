"use strict";

(() => {
  const form = document.querySelector("[data-workout-form]");
  if (!form) return;
  const list = form.querySelector("#log-exercises");
  const { tr } = window.evolveI18n;
  const cache = new Map();
  const states = new WeakMap();
  const nameOf = (row) => row.querySelector('[name="exercise_name"]').value.trim();
  const keyOf = (row) => nameOf(row).toLocaleLowerCase();
  const number = (row, field) => Number(row.querySelector(`[name="exercise_${field}"]`)?.value || 0);
  const display = (value) => Number(value.toFixed(2));

  function render(row) {
    const state = states.get(row);
    if (!state) return;
    const history = state.history;
    const holder = row.querySelector("[data-exercise-history]");
    const change = row.querySelector("[data-volume-change]");
    holder.replaceChildren();
    change.textContent = "";
    if (!history || !Object.keys(history).length) return;
    const bodyweight = row.querySelector('[name="exercise_load_type"]').value === "bodyweight";
    if (!bodyweight) {
      const options = [
        [tr("Average"), history.average_weight_kg],
        [tr("Last workout"), history.last_weight_kg],
        [tr("Last +10%"), history.plus_ten_weight_kg],
      ];
      for (const [label, value] of options) {
        if (value == null) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "exercise-history-option";
        button.textContent = `${label}: ${value} kg`;
        button.addEventListener("click", () => {
          const input = row.querySelector('[name="exercise_weight"]');
          input.value = value;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        });
        holder.append(button);
      }
    }
    if (history.last_volume_kg > 0) {
      const matching = [...list.querySelectorAll(".log-exercise-row")].filter((item) => keyOf(item) === keyOf(row));
      const current = matching.reduce((sum, item) => {
        if (item.querySelector('[name="exercise_measurement"]').value === "time") return sum;
        const effectiveWeight = item.querySelector('[name="exercise_load_type"]').value === "bodyweight"
          ? Number(form.dataset.bodyweight) * number(item, "bodyweight_percent") / 100
          : number(item, "weight");
        return sum + number(item, "sets") * number(item, "reps") * effectiveWeight;
      }, 0);
      if (current > 0) {
        const percent = display((current / history.last_volume_kg - 1) * 100);
        const sign = percent > 0 ? "+" : "";
        change.textContent = tr("Volume vs last time: {change}% ({current} kg vs {previous} kg)", {
          change: `${sign}${percent}`, current: display(current), previous: history.last_volume_kg,
        });
      }
    }
  }

  async function load(row) {
    const state = states.get(row);
    const name = nameOf(row);
    const version = ++state.version;
    state.name = name;
    if (!name || name.length > 100) { state.history = null; render(row); return; }
    const key = name.toLocaleLowerCase();
    if (!cache.has(key)) {
      const url = `${form.dataset.historyUrl}?${new URLSearchParams({ name })}`;
      cache.set(key, fetch(url, { headers: { Accept: "application/json" } })
        .then((response) => { if (!response.ok) throw new Error("History unavailable"); return response.json(); })
        .catch(() => { cache.delete(key); return null; }));
    }
    const history = await cache.get(key);
    if (version !== state.version || !row.isConnected) return;
    state.history = history;
    render(row);
  }

  function initialize(row) {
    if (states.has(row)) return;
    let history = null;
    try { history = JSON.parse(row.dataset.history || "null"); } catch { /* Fetch below. */ }
    states.set(row, { name: nameOf(row), history, version: 0, timer: null });
    if (history) render(row);
    else if (nameOf(row)) load(row);
  }
  [...list.children].forEach(initialize);
  new MutationObserver(() => [...list.children].forEach(initialize)).observe(list, { childList: true });
  function changed(event) {
    const row = event.target.closest(".log-exercise-row");
    if (!row) return;
    initialize(row);
    const state = states.get(row);
    if (event.target.name === "exercise_name" && nameOf(row) !== state.name) {
      clearTimeout(state.timer);
      state.history = null;
      render(row);
      state.timer = setTimeout(() => load(row), 220);
    } else {
      [...list.children].forEach(render);
    }
  }
  list.addEventListener("input", changed);
  list.addEventListener("change", changed);
  list.addEventListener("compositionend", changed);
})();
