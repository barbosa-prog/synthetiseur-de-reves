"use strict";
(() => {
  const progress = document.getElementById("stt-progress");
  if (!progress || !["pending", "processing"].includes(progress.dataset.status)) return;
  const label = document.getElementById("stt-status");
  const button = document.getElementById("stt-start");
  const poll = async () => {
    if (document.hidden) { window.setTimeout(poll, 3000); return; }
    try {
      const response = await fetch(progress.dataset.url, {cache: "no-store", redirect: "error"});
      if (!response.ok) throw new Error("status");
      const job = await response.json();
      if (job.status === "completed") {
        label.textContent = "Transcription enregistrée. Vous pouvez vérifier et corriger le récit.";
        // Recharger avant toute nouvelle demande : sa version doit être à jour.
        label.append(document.createTextNode(" Rechargez cette page pour relancer une transcription."));
        return;
      }
      if (job.status === "failed") {
        label.textContent = job.message || "La transcription a échoué.";
        if (button) button.disabled = false;
        return;
      }
      label.textContent = job.status === "processing" ? "Transcription en cours…" : "En attente du worker local…";
      window.setTimeout(poll, 2000);
    } catch {
      label.textContent = "Suivi indisponible. Rechargez la page et vérifiez votre connexion. Votre demande reste enregistrée.";
    }
  };
  window.setTimeout(poll, 1000);
})();
