"""Validation commune des récits, sans journalisation ni interprétation HTML."""

MAX_TEXT_LENGTH = 20000


def normalize_text(value: str) -> str:
    """Compte les points Unicode après normalisation des fins de ligne, avant trim."""
    if not isinstance(value, str):
        raise ValueError("Le récit doit être un texte.")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError("Le récit ne doit pas dépasser 20 000 caractères.")
    if "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("Le récit contient un caractère non accepté.")
    value = value.strip()
    if not value:
        raise ValueError("Le récit ne peut pas être vide ou composé uniquement d’espaces.")
    return value
