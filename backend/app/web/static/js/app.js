"use strict";

// Aucun jeton d'authentification n'est lu, reçu ou conservé par ce script.
const toggle = document.getElementById("menu-toggle");
const navigation = document.getElementById("navigation");
toggle?.addEventListener("click", () => {
  const expanded = toggle.getAttribute("aria-expanded") === "true";
  toggle.setAttribute("aria-expanded", String(!expanded));
  navigation.classList.toggle("mobile-open", !expanded);
});

document.querySelectorAll("[data-auth-form]").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    button.textContent = "Un instant…";
  });
});

const protectedPage = document.querySelector("[data-protected-page]");
if (protectedPage) {
  const expired = () => window.location.replace("/connexion?etat=expiree");
  const remaining = Date.parse(protectedPage.dataset.expiresAt) - Date.now();
  window.setTimeout(expired, Math.max(0, remaining));
  const checkSession = async () => {
    if (document.visibilityState !== "visible") return;
    try {
      const response = await fetch("/web/session", {
        credentials: "same-origin", cache: "no-store", redirect: "manual",
      });
      if (response.type === "opaqueredirect" || response.status === 401) expired();
    } catch {
      // Une panne réseau n'est pas interprétée comme une déconnexion.
    }
  };
  window.setInterval(checkSession, 60000);
  document.addEventListener("visibilitychange", checkSession);
  window.addEventListener("pageshow", checkSession);
}
