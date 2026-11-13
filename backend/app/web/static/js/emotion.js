"use strict";
(() => {
  const root = document.getElementById("emotion-controller");
  if (!root) return;
  const labels = {heureux: "Heureux", stressant: "Stressant", neutre: "Neutre", triste: "Triste", autre: "Autre"};
  const suggestion = document.getElementById("emotion-suggestion");
  const accept = document.getElementById("emotion-accept");
  const request = document.getElementById("emotion-request");
  let revision = Number(root.dataset.revision);
  let busy = root.dataset.busy === "1";
  const initialJob = root.dataset.job;
  const freeze = () => {
    suggestion.hidden = true;
    accept.disabled = true;
    request.disabled = true;
    document.getElementById("emotion-reload").hidden = false;
    root.querySelectorAll("[data-job-action]").forEach(el => { el.disabled = true; });
  };
  DreamJobPolling.start({root, url: root.dataset.url, initialState: root.dataset.state,
    onUnavailable: () => { accept.disabled = true; request.disabled = true; },
    onGone: freeze,
    onState: state => {
      const ownCompletion = busy && !state.busy && state.revision === revision + 1 &&
        state.job_id === initialJob && ["done", "abstention", "failed"].includes(state.status);
      if (state.text_version !== Number(root.dataset.version) ||
          (state.revision !== revision && !ownCompletion)) {
        DreamJobPolling.controls(root, state.tracking, true);
        document.getElementById("emotion-status").textContent = state.message;
        freeze();
        return;
      }
      revision = state.revision;
      busy = state.busy;
      root.querySelectorAll("input[name=revision]").forEach(el => {
        el.value = `${state.text_version}:${revision}`;
      });
      DreamJobPolling.controls(root, state.tracking);
      document.getElementById("retained-emotion").textContent = state.value_label;
      document.getElementById("emotion-origin").textContent = state.origin_label;
      document.getElementById("emotion-status").textContent = state.message;
      document.getElementById("emotion-disabled").hidden = state.enabled;
      request.disabled = !state.enabled || !state.ready || busy || state.status === "failed";
      suggestion.hidden = !state.suggestion;
      accept.disabled = !state.suggestion || !state.suggestion.emotion;
      if (state.suggestion) {
        document.getElementById("suggested-emotion").textContent =
          labels[state.suggestion.emotion] || "Abstention — aucune émotion proposée";
        document.getElementById("suggestion-id").value = state.suggestion.request_id;
      }
    }
  });
})();
