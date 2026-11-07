"use strict";

(() => {
  const explorer = document.querySelector("[data-muscle-activity]");
  if (!explorer) return;
  const panels = [...explorer.querySelectorAll("[data-muscle-panel]")];
  const choices = [...explorer.querySelectorAll("[data-muscle-choice]")];
  const regions = [...explorer.querySelectorAll("[data-muscle-region]")];
  const select = (key) => {
    if (!panels.some((panel) => panel.dataset.musclePanel === key)) return;
    panels.forEach((panel) => { panel.hidden = panel.dataset.musclePanel !== key; });
    choices.forEach((choice) => {
      if (choice.dataset.muscleChoice === key) choice.setAttribute("aria-current", "true");
      else choice.removeAttribute("aria-current");
    });
    regions.forEach((region) => region.setAttribute("aria-pressed", String(region.dataset.muscleRegion === key)));
    const url = new URL(window.location.href);
    url.searchParams.set("muscle", key);
    window.history.replaceState(null, "", url);
    explorer.querySelectorAll(".muscle-periods a").forEach((link) => {
      const destination = new URL(link.href);
      destination.searchParams.set("muscle", key);
      link.href = destination.href;
    });
    if (window.matchMedia("(max-width: 600px)").matches) {
      explorer.querySelector(".muscle-details").scrollIntoView({
        block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
      });
    }
  };
  choices.forEach((choice) => choice.addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    select(choice.dataset.muscleChoice);
  }));
  regions.forEach((region) => {
    region.addEventListener("click", () => select(region.dataset.muscleRegion));
    region.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      select(region.dataset.muscleRegion);
    });
  });
})();
