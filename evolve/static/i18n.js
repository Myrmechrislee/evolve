"use strict";

// The same catalogue powers Jinja pages and dynamically created controls.
window.evolveI18n = (() => {
  const messages = JSON.parse(document.querySelector("#i18n-data").textContent);
  const workoutMessages = JSON.parse(document.querySelector("#workout-i18n-data").textContent);
  const tr = (message, values = {}) => (messages[message] ?? message).replace(/\{(\w+)\}/g,
    (placeholder, key) => Object.hasOwn(values, key) ? String(values[key]) : placeholder);
  const units = {"per side": "每侧", "each side": "每侧", "seconds": "秒", "second": "秒", "secs": "秒", "sec": "秒", "minutes": "分钟", "minute": "分钟", "reps": "次"};
  const workoutText = (text) => {
    const translated = workoutMessages[String(text).toLowerCase()];
    if (translated !== undefined) return translated;
    if (document.documentElement.lang !== "zh-Hans" || typeof text !== "string") return text;
    return text.replace(/\b(per side|each side|seconds?|secs?|minutes?|reps)\b/gi, (unit) => units[unit.toLowerCase()]);
  };
  return { tr, workoutText };
})();

document.querySelectorAll("[data-language-switch]").forEach((form) => {
  form.addEventListener("submit", () => {
    form.elements.next.value = location.pathname + location.search + location.hash;
  });
});

document.querySelector("[data-workout-translation-form]")?.addEventListener("submit", (event) => {
  event.currentTarget.querySelector("button").disabled = true;
  event.currentTarget.querySelector("[data-translation-status]").hidden = false;
});

// Show translations alongside editable originals, so merely viewing or saving
// in another language cannot rename exercises or break existing draft targets.
if (document.documentElement.lang === "zh-Hans") {
  const selector = '[data-exercise-name], [data-session-title], [name="plan_name"], [name="plan_goal"], [data-field="notes"], [data-field="reps"], [name="notes"], [name="title"]';
  const labels = new WeakMap();
  const update = (input) => {
    if (!input.matches?.(selector)) return;
    const translated = window.evolveI18n.workoutText(input.value);
    let label = labels.get(input);
    if (!label) {
      label = document.createElement("span");
      label.className = "field-help workout-field-translation";
      input.after(label);
      labels.set(input, label);
    }
    label.textContent = translated;
    label.hidden = !translated || translated === input.value;
  };
  const scan = (root) => {
    if (root.matches?.(selector)) update(root);
    root.querySelectorAll(selector).forEach(update);
  };
  scan(document.querySelector("#main"));
  new MutationObserver((mutations) => mutations.forEach((mutation) => {
    mutation.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) scan(node);
    });
  })).observe(document.querySelector("#main"), {childList: true, subtree: true});
  document.addEventListener("input", (event) => update(event.target));
  document.addEventListener("change", (event) => update(event.target));
}
