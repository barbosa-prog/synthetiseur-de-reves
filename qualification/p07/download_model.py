"""Préparation explicite des seuls fichiers SD 1.5 FP16, après accord utilisateur."""

import argparse
import json

from common import (
    FILES,
    REPOSITORY,
    REVISION,
    WEIGHTS,
    QualificationError,
    digest,
    exclusive,
    free_disk_gib,
    paths,
    ram_mib,
    require_environment,
    verify_model,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorize-download", action="store_true")
    parser.add_argument("--accept-openrail-license", action="store_true")
    args = parser.parse_args()
    if not args.authorize_download or not args.accept_openrail_license:
        parser.error("Accord de téléchargement et acceptation de licence explicites requis.")
    require_environment()
    with exclusive():
        target = paths()[2]
        if (target / "qualification-manifest.json").is_file():
            verify_model()
            print("Modèle déjà présent et vérifié : aucun accès réseau.")
            return
        if ram_mib() < 1024 or free_disk_gib() < 15:
            raise QualificationError("Prévoir 1 Gio de RAM et 15 Gio de disque libres.")
        from huggingface_hub import HfApi, snapshot_download
        info = HfApi(token=False).model_info(REPOSITORY, revision=REVISION, files_metadata=True)
        remote = {item.rfilename: item for item in info.siblings}
        if info.sha != REVISION or any(remote[name].size != size for name, size in WEIGHTS.items()):
            raise QualificationError("Révision ou tailles différentes de la proposition.")
        snapshot_download(REPOSITORY, revision=REVISION, local_dir=target,
                          allow_patterns=FILES, token=False, max_workers=1)
        hashes = {}
        for name in FILES:
            item = target / name
            if not item.is_file():
                raise QualificationError("Fichier requis absent ; reprise explicite nécessaire.")
            hashes[name] = digest(item)
            lfs = remote[name].lfs
            if lfs is not None and hashes[name] != lfs.sha256:
                raise QualificationError("Empreinte différente de la référence Hugging Face.")
        manifest = {"repository": REPOSITORY, "revision": REVISION, "files": hashes,
                    "license": "CreativeML OpenRAIL-M",
                    "license_url": "https://huggingface.co/spaces/CompVis/stable-diffusion-license"}
        temporary = target / "qualification-manifest.tmp"
        temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        temporary.replace(target / "qualification-manifest.json")
        verify_model()
        print("Modèle FP16 complet et vérifié ; filtre de sécurité inclus.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, QualificationError) else type(exc).__name__
        print(f"Préparation arrêtée : {detail}")
        raise SystemExit(1) from None
