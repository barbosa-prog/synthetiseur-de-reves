"""Limites et contrats internes P04, sans moteur de transcription."""

MAX_UPLOAD = 15 * 1024 * 1024
MAX_SECONDS = 480
SAMPLE_RATE = 16000
FORMATS = {"wav", "mp3", "webm", "ogg", "mp4"}
MAX_SAMPLES = MAX_SECONDS * SAMPLE_RATE


class AudioError(Exception):
    """Erreur publique sans donnée audio ni chemin privé."""

    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)
