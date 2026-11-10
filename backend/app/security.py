"""Primitives Argon2id et jetons opaques ; aucune journalisation de secrets."""

import hashlib
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
# Vérification factice pour un compte absent ou hérité de P02 sans mot de passe.
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Hache avec un sel aléatoire ; ne jamais journaliser l'argument."""
    return hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Vérifie sans divulguer si un compte existe."""
    try:
        valid = hasher.verify(stored_hash or DUMMY_HASH, password)
        return bool(stored_hash) and valid
    except (VerificationError, InvalidHashError):
        return False


def token_digest(token: str) -> str:
    """Condensat d'un jeton de 256 bits ; le jeton brut n'est jamais conservé en base."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    """Produit 32 octets cryptographiquement aléatoires encodés URL-safe."""
    return secrets.token_urlsafe(32)
