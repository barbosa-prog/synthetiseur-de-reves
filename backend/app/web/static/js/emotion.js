"use strict";
(() => {
  const root = document.getElementById("emotion-controller");
  if (!root) return;
  const labels = {heureux: "Heureux", stressant: "Stressant", neutre: "Neutre", triste: "Triste", autre: "Autre"};
  const suggestion = document.getElementById("emotion-suggestion");
  const accept = document.getElementById("emotion-accept");
  let revision = Number(root.dataset.revision);
  let busy = root.dataset.busy === "1";
  const initialJob = root.dataset.job;
  const freeze = (message) => {
    suggestion.hidden = true;
    accept.disabled = true;
    const warning = document.getElementById("emotion-reload");
    if (message) warning.textContent = message;
    warning.hidden = false;
    root.querySelectorAll("button,select").forEach(el => { el.disabled = true; });
  };
  const poll = async () => {
    if (document.hidden) { setTimeout(poll, 3000); return; }
    try {
      const response = await fetch(root.dataset.url, {cache: "no-store", redirect: "error"});
      if (!response.ok) throw new Error("status");
      const state = await response.json();
      if (state.text_version !== Number(root.dataset.version)) { freeze(); return; }
      const ownCompletion = busy && !state.busy && state.revision === revision + 1 && state.job_id === initialJob &&
        ["done", "abstention", "failed"].includes(state.status);
      if (state.revision !== revision && !ownCompletion) { freeze(); return; }
      revision = state.revision;
      busy = state.busy;
      root.querySelectorAll("input[name=revision]").forEach(el => { el.value = `${state.text_version}:${revision}`; });
      document.getElementById("retained-emotion").textContent = state.value_label;
      document.getElementById("emotion-origin").textContent = state.origin_label;
      document.getElementById("emotion-status").textContent = state.message;
      document.getElementById("emotion-disabled").hidden = state.enabled;
      document.getElementById("emotion-request").disabled = !state.enabled || !state.ready || busy;
      suggestion.hidden = !state.suggestion;
      accept.disabled = !state.suggestion || !state.suggestion.emotion;
      if (state.suggestion) {
        document.getElementById("suggested-emotion").textContent =
          labels[state.suggestion.emotion] || "Abstention — aucune émotion proposée";
        document.getElementById("suggestion-id").value = state.suggestion.request_id;
      }
      setTimeout(poll, 2000);
    } catch {
      freeze("Vérification indisponible. Rechargez la page avant de continuer.");
    }
  };
  setTimeout(poll, 1000);
})();
