"use strict";

const editorForm = document.getElementById("transcript-form");
if (editorForm) {
  const editor = document.getElementById("transcript");
  const counter = document.getElementById("text-count");
  const warning = document.getElementById("client-text-error");
  const hint = document.getElementById("save-hint");
  const initial = editor.value;
  const initiallyUnsaved = editorForm.dataset.unsaved === "true";
  let dirty = initiallyUnsaved, submitting = false;
  const update = (showWarning) => {
    const size = Array.from(editor.value.replace(/\r\n?/g, "\n")).length;
    counter.textContent = `${size.toLocaleString("fr-FR")} / 20 000`;
    const message = !editor.value.trim() ? "Le récit ne peut pas être vide." :
      (size > 20000 ? "Le récit dépasse la limite de 20 000 caractères." : "");
    editor.setCustomValidity(message);
    warning.textContent = message;
    warning.hidden = !showWarning || !message;
  };
  editor.addEventListener("input", () => {
    dirty = initiallyUnsaved || editor.value !== initial;
    hint.textContent = dirty ? "Modifications non enregistrées." : "Aucune nouvelle modification.";
    update(true);
  });
  editor.addEventListener("invalid", () => update(true));
  editorForm.addEventListener("submit", () => { submitting = true; });
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !submitting) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  // Aucune autosauvegarde ni copie dans un stockage persistant du navigateur.
  update(false);
}
