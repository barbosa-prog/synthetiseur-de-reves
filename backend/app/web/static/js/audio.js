"use strict";

const capture = document.getElementById("audio-capture");
if (capture) {
  const byId = (id) => document.getElementById(id);
  const maxBytes = 15 * 1024 * 1024;
  const error = byId("audio-error"), status = byId("audio-status");
  const preview = byId("audio-preview"), review = byId("audio-review");
  let recorder, stream, chunks = [], candidate, objectUrl, timer, startedAt, bytes = 0;
  let mode = "microphone", selectedFormat, recording = false, busy = false, rejected = false;
  const showError = (message) => { error.textContent = message; error.hidden = false; };
  const clearError = () => { error.hidden = true; error.textContent = ""; };
  const releaseStream = () => { stream?.getTracks().forEach((track) => track.stop()); stream = null; };
  const clearPreview = () => {
    preview.pause(); preview.removeAttribute("src"); preview.load();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null; candidate = null; chunks = []; review.hidden = true;
  };
  const setPreview = (blob, filename, format) => {
    clearPreview(); candidate = {blob, filename, format};
    objectUrl = URL.createObjectURL(blob); preview.src = objectUrl; review.hidden = false;
    status.textContent = "Audio prêt à être écouté. Confirmez pour l’enregistrer.";
  };
  const updateControls = () => {
    byId("record-start").disabled = busy || recording;
    byId("record-stop").disabled = busy || !recording;
    ["mode-micro", "mode-file", "audio-file", "audio-reset", "audio-confirm"].forEach((id) => {
      byId(id).disabled = busy || recording;
    });
  };
  const stopRecording = () => {
    if (recorder && recorder.state !== "inactive") recorder.stop();
    clearInterval(timer);
    releaseStream();
  };
  const chooseMode = (value) => {
    if (busy || recording) return;
    mode = value; clearPreview(); clearError();
    byId("micro-panel").hidden = value !== "microphone";
    byId("file-panel").hidden = value !== "import";
    byId("mode-micro").setAttribute("aria-pressed", String(value === "microphone"));
    byId("mode-file").setAttribute("aria-pressed", String(value === "import"));
    [["mode-micro", value === "microphone"], ["mode-file", value === "import"]].forEach(([id, active]) => {
      byId(id).classList.toggle("btn-primary", active);
      byId(id).classList.toggle("btn-secondary", !active);
    });
    status.textContent = value === "microphone" ? "Prêt à enregistrer." : "Choisissez un fichier WAV ou MP3.";
  };
  byId("mode-micro").addEventListener("click", () => chooseMode("microphone"));
  byId("mode-file").addEventListener("click", () => chooseMode("import"));
  byId("record-start").addEventListener("click", async () => {
    clearError(); clearPreview();
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      showError("Ce navigateur ne permet pas l’enregistrement ici. Utilisez HTTPS ou importez un WAV/MP3."); return;
    }
    const formats = [
      ["audio/webm;codecs=opus", "webm"], ["audio/ogg;codecs=opus", "ogg"],
      ["audio/mp4", "mp4"], ["audio/webm", "webm"],
    ];
    const supported = formats.find(([mime]) => MediaRecorder.isTypeSupported(mime));
    if (!supported) { showError("Aucun format d’enregistrement compatible. Importez un WAV ou MP3."); return; }
    busy = true; updateControls(); status.textContent = "Autorisez l’accès au microphone…";
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
      selectedFormat = supported[1];
      recorder = new MediaRecorder(stream, {mimeType: supported[0]});
      chunks = []; bytes = 0; rejected = false;
      recorder.addEventListener("dataavailable", (event) => {
        bytes += event.data.size;
        if (bytes > maxBytes) {
          rejected = true; chunks = []; stopRecording(); showError("L’enregistrement dépasse 15 Mio. Recommencez avec un audio plus court.");
        } else if (!rejected && event.data.size) chunks.push(event.data);
      });
      recorder.addEventListener("stop", () => {
        recording = false; busy = false; clearInterval(timer); releaseStream(); updateControls();
        if (!rejected && bytes > 0) setPreview(new Blob(chunks, {type: recorder.mimeType}), `enregistrement.${selectedFormat}`, selectedFormat);
        else if (!rejected) showError("Aucun son n’a été enregistré. Réessayez.");
      });
      recorder.addEventListener("error", () => {
        rejected = true; stopRecording(); showError("L’enregistrement a été interrompu par le navigateur.");
      });
      recorder.start(500); recording = true; busy = false; startedAt = Date.now(); updateControls();
      status.textContent = "Enregistrement en cours. Rien n’est encore envoyé.";
      timer = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startedAt) / 1000);
        byId("recording-time").textContent = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;
        if (elapsed >= 480) stopRecording();
      }, 250);
    } catch (exception) {
      releaseStream(); busy = false; recording = false; updateControls();
      const messages = {
        NotAllowedError: "Accès au microphone refusé. Autorisez-le dans le navigateur ou importez un WAV/MP3.",
        NotFoundError: "Aucun microphone disponible. Vous pouvez importer un WAV ou MP3.",
        NotReadableError: "Le microphone est indisponible ou utilisé par une autre application.",
      };
      showError(messages[exception.name] || "Impossible de démarrer le microphone. Essayez l’import de fichier.");
    }
  });
  byId("record-stop").addEventListener("click", stopRecording);
  byId("audio-file").addEventListener("change", (event) => {
    clearError(); clearPreview();
    const file = event.target.files[0];
    if (!file) return;
    const extension = file.name.split(".").pop().toLowerCase();
    if (!["wav", "mp3"].includes(extension)) { showError("Choisissez uniquement un fichier WAV ou MP3."); return; }
    if (!file.size) { showError("Le fichier audio est vide."); return; }
    if (file.size > maxBytes) { showError("Le fichier dépasse la limite de 15 Mio."); return; }
    setPreview(file, file.name, extension);
  });
  byId("audio-reset").addEventListener("click", () => {
    clearPreview(); clearError(); byId("audio-file").value = ""; byId("recording-time").textContent = "00:00";
    status.textContent = "Prêt pour un nouvel audio.";
  });
  byId("audio-confirm").addEventListener("click", async () => {
    if (!candidate || busy) return;
    busy = true; updateControls(); clearError(); status.textContent = "Envoi privé, vérification et conversion locale…";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const response = await fetch("/web/audio", {
        method: "POST", credentials: "same-origin", redirect: "manual", signal: controller.signal,
        headers: {"Content-Type": "application/octet-stream", "X-CSRF-Token": capture.dataset.csrf,
          "X-Audio-Format": candidate.format, "X-Audio-Source": mode,
          "X-Audio-Filename": encodeURIComponent(candidate.filename)},
        body: candidate.blob,
      });
      if (response.type === "opaqueredirect" || response.status === 401) {
        window.location.replace("/connexion?etat=expiree"); return;
      }
      const data = await response.json();
      if (!response.ok) {
        showError(response.status === 403 ? "La protection de session a expiré. Rechargez la page avant de réessayer." : (data.error?.message || "L’audio n’a pas pu être enregistré."));
        status.textContent = "Audio non enregistré."; return;
      }
      window.location.assign(`/reves/${data.dream_id}/audio`);
    } catch (exception) {
      showError(exception.name === "AbortError" ? "L’envoi a dépassé le délai. Vérifiez votre connexion avant de réessayer." : "Envoi interrompu. Aucun résultat n’a pu être confirmé.");
    } finally { clearTimeout(timeout); busy = false; updateControls(); }
  });
  window.addEventListener("pagehide", () => {
    rejected = true; stopRecording(); clearPreview();
  });
}
