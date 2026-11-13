"use strict";
(() => {
  const root = document.getElementById("image-controller");
  const progress = document.getElementById("image-progress");
  if (!root || !progress) return;
  const input = document.getElementById("image-description");
  const generate = document.getElementById("image-generate");
  const count = document.getElementById("image-count");
  const label = document.getElementById("image-status");
  const figure = document.getElementById("image-result");
  const image = document.getElementById("dream-image");
  const refresh = document.getElementById("image-refresh");
  const initial = input ? input.value : "";
  let blocked = generate ? generate.disabled : true;
  let disconnected = false;
  const actions = new Map(Array.from(root.querySelectorAll("[data-job-action]"),
    el => [el, !el.disabled]));
  const update = () => {
    if (count && input) count.textContent = `${Array.from(input.value).length} / 500 caractères`;
    if (generate) generate.disabled = blocked || Boolean(input && input.value !== initial);
    const changed = Boolean(input && input.value !== initial);
    root.querySelectorAll("[data-job-action]").forEach(el => {
      el.disabled = disconnected || changed || !actions.get(el);
    });
  };
  if (input) input.addEventListener("input", update);
  update();
  const unavailable = () => {
    disconnected = true;
    blocked = true;
    update();
    figure.hidden = true;
    image.removeAttribute("src");
  };
  DreamJobPolling.start({root, url: progress.dataset.url, initialState: root.dataset.state,
    onUnavailable: unavailable, onGone: unavailable,
    onState: state => {
      disconnected = false;
      const changed = String(state.text_version) !== progress.dataset.textVersion ||
        String(state.description_version) !== progress.dataset.descriptionVersion;
      blocked = changed || !state.ready || state.busy || state.status === "failed";
      DreamJobPolling.controls(root, state.tracking, changed);
      root.querySelectorAll("[data-job-action]").forEach(el => actions.set(el, !el.disabled));
      update();
      refresh.hidden = !changed && state.ready;
      label.textContent = state.message;
      if (state.image_url && !state.tracking?.outdated && !changed) {
        if (image.getAttribute("src") !== state.image_url) image.src = state.image_url;
        figure.hidden = false;
      } else {
        figure.hidden = true;
        image.removeAttribute("src");
      }
    }
  });
})();
