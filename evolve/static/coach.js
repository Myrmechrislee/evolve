"use strict";

(() => {
  const form = document.querySelector("#chat-form");
  if (!form) return;
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const area = document.querySelector("#draft-area");
  const messages = document.querySelector("#chat-messages");
  const input = document.querySelector("#chat-input");
  const status = document.querySelector("#chat-status");
  const send = document.querySelector("#chat-send");
  function addMessage(role, content) {
    const message = document.createElement("div");
    message.className = `chat-message ${role}`;
    const label = document.createElement("span");
    label.className = "message-label";
    label.textContent = role === "user" ? "YOU" : "EVOLVE COACH";
    const body = document.createElement("p");
    body.textContent = content;
    message.append(label, body);
    messages.append(message);
    messages.scrollTop = messages.scrollHeight;
  }
  function renderDraft(draft) {
    const card = document.createElement("section");
    card.className = "card draft-card";
    card.innerHTML = `<span class="eyebrow">YOUR PROPOSED PLAN</span><h2></h2><p></p><div class="draft-summary"></div><div class="draft-sessions"></div><form method="post"><input type="hidden" name="csrf_token"><label>Start date<input type="date" name="start_date" required><span class="field-help">Choose today or a future date. Week 1 runs for 7 days from this date. Existing plans with logged workouts keep their start date.</span></label><button class="button"></button></form><p class="draft-note">Review all sessions above. You can edit any detail manually after applying. Drafts expire after 7 days.</p>`;
    card.querySelector("h2").textContent = draft.content.name;
    card.querySelector("p").textContent = draft.content.goal;
    card.querySelector(".draft-summary").textContent = `${draft.content.weeks} weeks · ${draft.content.sessions.length} sessions per week`;
    draft.content.sessions.forEach((session) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${session.day} · ${session.title}`;
      const list = document.createElement("ul");
      session.exercises.forEach((exercise) => {
        const li = document.createElement("li");
        li.textContent = `${exercise.name} · ${exercise.sets} × ${exercise.reps} · ${exercise.rest_seconds}s rest`;
        if (exercise.notes) {
          const note = document.createElement("span");
          note.textContent = exercise.notes;
          li.append(note);
        }
        const hint = document.createElement("div");
        hint.dataset.exerciseHintName = exercise.name;
        li.append(hint);
        list.append(li);
      });
      details.append(summary, list);
      card.querySelector(".draft-sessions").append(details);
    });
    card.querySelector("form").action = `/coach/drafts/${encodeURIComponent(draft.id)}/apply`;
    card.querySelector('[name="csrf_token"]').value = token;
    card.querySelector('[name="start_date"]').value = draft.start_date;
    card.querySelector("button").textContent = form.dataset.planId ? "Apply changes to plan →" : "Use this workout plan →";
    area.replaceChildren(card);
  }
  const initial = document.querySelector("#initial-draft");
  if (initial) renderDraft(JSON.parse(initial.textContent));
  messages.scrollTop = messages.scrollHeight;
  document.querySelector("#coach-target").addEventListener("change", (event) => {
    window.location.href = event.target.value ? `/coach?plan_id=${encodeURIComponent(event.target.value)}` : "/coach";
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || send.disabled) return;
    send.disabled = true;
    input.disabled = true;
    status.classList.remove("error");
    status.textContent = "Your coach is thinking… This can take a minute.";
    try {
      const response = await fetch("/api/coach/chat", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ message, plan_id: form.dataset.planId || null, share_profile: document.querySelector("#share-profile").checked }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "The coach could not respond. Please try again.");
      addMessage("user", message);
      addMessage("assistant", result.reply);
      input.value = "";
      if (result.draft) renderDraft(result.draft);
      status.textContent = result.draft ? "Your draft is ready to review. No plan has been changed." : "What else would you like to work on?";
    } catch (error) {
      status.textContent = error.message || "Connection interrupted. Please try again.";
      status.classList.add("error");
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus();
    }
  });
})();
