"""Certificats HTTPS locaux de développement ; aucune installation dans Windows."""

from pathlib import Path

import trustme


def main() -> None:
    """Écrit dans tmp ignoré par Git ; autorité éphémère, certificat local non public."""
    directory = Path(__file__).resolve().parents[1] / "tmp/https"
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in ("cert.pem", "key.pem", "ca.pem")):
        raise SystemExit("Certificats déjà présents ; aucun fichier écrasé.")
    authority = trustme.CA()
    certificate = authority.issue_cert("localhost", "127.0.0.1")
    certificate.private_key_pem.write_to_path(directory / "key.pem")
    certificate.cert_chain_pems[0].write_to_path(directory / "cert.pem")
    authority.cert_pem.write_to_path(directory / "ca.pem")
    print("Certificat de développement créé dans tmp/https ; aucune autorité installée.")


if __name__ == "__main__":
    main()
