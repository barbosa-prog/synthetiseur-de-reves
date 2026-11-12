"use strict";
(() => {
  const section = document.getElementById("current-image-section");
  if (!section) return;
  const panel = document.getElementById("current-image-panel");
  const image = document.getElementById("current-dream-image");
  const empty = document.getElementById("no-current-image");
  const hide = () => { panel.hidden = true; image.removeAttribute("src"); empty.hidden = false; };
  const poll = async () => {
    if (document.hidden) { window.setTimeout(poll, 3000); return; }
    try {
      const response = await fetch(section.dataset.statusUrl, {cache: "no-store", redirect: "error"});
      if (!response.ok) throw new Error("status");
      const state = await response.json();
      if (state.image_url) {
        if (image.getAttribute("src") !== state.image_url) image.src = state.image_url;
        panel.hidden = false;
        empty.hidden = true;
      } else hide();
      window.setTimeout(poll, 2000);
    } catch {
      hide();
      empty.textContent = "Vérification de l’image indisponible. Rechargez la page avant de continuer.";
    }
  };
  window.setTimeout(poll, 1000);
})();
