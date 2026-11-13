"use strict";
(() => {
  const active = state => ["queued", "running"].includes(state);
  const controls = (root, tracking, blocked = false) => {
    const panel = root.querySelector("[data-job-controls]");
    if (!panel || !tracking) return;
    panel.querySelector("[data-job-canonical]").textContent = tracking.state_label;
    panel.querySelector("[data-job-budget]").textContent = tracking.budget_known
      ? `Exécutions du cycle : ${tracking.cycle_attempts} / ${tracking.max_attempts}. Relances manuelles : ${tracking.retry_count} / ${tracking.max_manual_retries}. ${tracking.retries_remaining} relance(s) restante(s).`
      : "Budget inconnu pour cet ancien traitement. Relance indisponible.";
    panel.querySelector("[data-job-safe-message]").textContent = tracking.state_message;
    const revision = `${tracking.job_id}:${tracking.retry_count}:${tracking.cycle_attempts}:${tracking.technical_state}`;
    if (revision !== panel.dataset.actionRevision) {
      panel.querySelectorAll("input[type=checkbox]").forEach(el => { el.checked = false; });
      panel.dataset.actionRevision = revision;
    }
    for (const [selector, permitted, url] of [
      ["[data-job-retry]", tracking.retryable, tracking.retry_url],
      ["[data-job-regenerate]", tracking.regeneratable, tracking.regenerate_url]
    ]) {
      const form = panel.querySelector(selector);
      if (!form) continue;
      form.hidden = !permitted;
      form.action = url;
      form.querySelector("input[name=expected]").value = tracking.confirmation;
      form.querySelector("button").disabled = blocked || !permitted;
    }
  };
  const network = (root, message) => {
    const panel = root.querySelector("[data-job-controls]");
    if (!panel) return;
    const warning = panel.querySelector("[data-job-network]");
    warning.textContent = message || "";
    warning.hidden = !message;
    if (message) panel.querySelectorAll("[data-job-action]").forEach(el => { el.disabled = true; });
  };
  const start = ({root, url, initialState, onState, onUnavailable, onGone}) => {
    let timer = null, request = null, failures = 0, disposed = false;
    let terminal = !active(initialState);
    const schedule = delay => {
      clearTimeout(timer);
      if (!disposed) timer = setTimeout(check, delay);
    };
    const check = async () => {
      if (disposed || request) return;
      if (document.hidden) { if (!terminal) schedule(3000); return; }
      clearTimeout(timer);
      request = new AbortController();
      const deadline = setTimeout(() => request?.abort(), 8000);
      try {
        const response = await fetch(url, {method: "GET", credentials: "same-origin",
          cache: "no-store", redirect: "error", signal: request.signal,
          headers: {"Accept": "application/json"}});
        if ([401, 403, 404].includes(response.status)) {
          disposed = true;
          network(root, "Session expirée ou rêve inaccessible. Rechargez la page.");
          onGone?.();
          return;
        }
        if (!response.ok) throw new Error("unavailable");
        const state = await response.json();
        const tracking = state.tracking;
        if (tracking && !["queued", "running", "done", "failed"].includes(tracking.technical_state)) {
          throw new Error("invalid-state");
        }
        failures = 0;
        network(root, "");
        onState(state);
        terminal = !active(tracking?.technical_state);
        if (!terminal) schedule(2000);
      } catch {
        if (disposed) return;
        failures = Math.min(failures + 1, 4);
        network(root, "Suivi momentanément indisponible. Nouvelle vérification automatique ; aucun traitement relancé.");
        onUnavailable?.();
        schedule(Math.min(15000, 1000 * 2 ** failures));
      } finally {
        clearTimeout(deadline);
        request = null;
      }
    };
    // Un retour sur l'onglet effectue une vérification ponctuelle, même après un état terminal.
    const resume = () => { if (!document.hidden && !disposed) check(); };
    window.addEventListener("online", resume);
    window.addEventListener("focus", resume);
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("pagehide", () => {
      disposed = true;
      clearTimeout(timer);
      request?.abort();
    });
    window.addEventListener("pageshow", event => {
      if (event.persisted) {
        disposed = false;
        // Retour depuis le cache de navigation : contrôle ponctuel, sans mutation.
        schedule(100);
      }
    });
    if (!terminal) schedule(1000);
  };
  window.DreamJobPolling = Object.freeze({start, controls, network});
})();
