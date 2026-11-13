"use strict";
(() => {
  const root = document.getElementById("stt-controller");
  const progress = document.getElementById("stt-progress");
  if (!root || !progress) return;
  const label = document.getElementById("stt-status");
  const button = document.getElementById("stt-start");
  const offline = () => { if (button) button.disabled = true; };
  DreamJobPolling.start({root, url: progress.dataset.url, initialState: root.dataset.state,
    onUnavailable: offline, onGone: offline,
    onState: job => {
      DreamJobPolling.controls(root, job.tracking);
      const active = ["queued", "running"].includes(job.tracking.technical_state);
      const changed = String(job.tracking.text_version) !== root.dataset.version;
      if (button) button.disabled = active || changed || job.status === "completed" ||
        (job.status === "failed" && !job.tracking.outdated);
      label.textContent = job.status === "completed"
        ? "Transcription enregistrée. Vous pouvez vérifier et corriger le récit. Rechargez avant une nouvelle demande."
        : job.tracking.state_message;
    }
  });
})();
