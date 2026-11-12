"use strict";
(() => {
  const progress = document.getElementById("image-progress");
  if (!progress) return;
  const input = document.getElementById("image-description");
  const generate = document.getElementById("image-generate");
  const count = document.getElementById("image-count");
  const label = document.getElementById("image-status");
  const figure = document.getElementById("image-result");
  const image = document.getElementById("dream-image");
  const refresh = document.getElementById("image-refresh");
  const initial = input ? input.value : "";
  let blocked = generate ? generate.disabled : true;
  const update = () => {
    if (count && input) count.textContent = `${Array.from(input.value).length} / 500 caractères`;
    if (generate) generate.disabled = blocked || (input && input.value !== initial);
  };
  if (input) input.addEventListener("input", update);
  update();
  const poll = async () => {
    if (document.hidden) { window.setTimeout(poll, 3000); return; }
    try {
      const response = await fetch(progress.dataset.url, {cache: "no-store", redirect: "error"});
      if (!response.ok) throw new Error("status");
      const state = await response.json();
      const changed = String(state.text_version) !== progress.dataset.textVersion ||
        String(state.description_version) !== progress.dataset.descriptionVersion;
      blocked = changed || !state.ready || state.busy;
      update();
      refresh.hidden = !changed && state.ready;
      label.textContent = state.message;
      if (state.image_url) {
        // URL construite par le serveur ; aucun contenu utilisateur injecté en HTML.
        if (image.getAttribute("src") !== state.image_url) image.src = state.image_url;
        figure.hidden = false;
      } else {
        figure.hidden = true;
        image.removeAttribute("src");
      }
      window.setTimeout(poll, 2000);
    } catch {
      blocked = true;
      update();
      figure.hidden = true;
      image.removeAttribute("src");
      label.textContent = "Suivi indisponible ou session expirée. Rechargez la page pour continuer. Aucun nouvel essai automatique.";
    }
  };
  window.setTimeout(poll, 1000);
})();
