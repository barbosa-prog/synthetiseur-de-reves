"""Téléchargement explicite du seul candidat, révision et fichiers bornés."""

import hashlib
import json
import os
import urllib.request
from pathlib import Path

REPO = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
REVISION = "0a71e92a985b6e1ad1828cf67ce9c459639c1dca"
FILES = ["README.md", "config.json", "tokenizer.json", "tokenizer_config.json",
         "special_tokens_map.json", "model.safetensors"]


def main(*, root=None, repo=REPO, revision=REVISION, files=FILES):
    root = root or Path(os.environ["LOCALAPPDATA"])/"SynthetiseurDeReves/qualification/p08/model"
    root.mkdir(parents=True, exist_ok=True)
    endpoint = f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
    with urllib.request.urlopen(endpoint, timeout=60) as response:
        metadata = json.load(response)
    if metadata["sha"] != revision or metadata["cardData"]["license"] != "mit":
        raise RuntimeError("Provenance ou licence inattendue")
    siblings = {item["rfilename"]: item for item in metadata["siblings"]}
    manifest = dict(repo=repo, revision=revision, license="mit", files={})
    for name in files:
        info = siblings[name]
        target = root/name
        expected_size = info["size"]
        if not target.exists():
            temporary = target.with_suffix(target.suffix+".part")
            try:
                url = f"https://huggingface.co/{repo}/resolve/{revision}/{name}"
                with (urllib.request.urlopen(url, timeout=120) as response,
                      temporary.open("wb") as out):
                    total = 0
                    while block := response.read(1024*1024):
                        total += len(block)
                        if total > expected_size:
                            raise RuntimeError("Taille dépassée")
                        out.write(block)
                if total != expected_size:
                    raise RuntimeError("Fichier incomplet")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if target.stat().st_size != expected_size:
            raise RuntimeError("Fichier local incohérent")
        with target.open("rb") as local:
            digest = hashlib.file_digest(local, "sha256").hexdigest()
        lfs_hash = info.get("lfs", {}).get("sha256")
        if lfs_hash and digest != lfs_hash:
            raise RuntimeError("Empreinte LFS incohérente")
        manifest["files"][name] = dict(bytes=expected_size, sha256=digest,
                                      lfs_verified=bool(lfs_hash))
        print(name, expected_size, "octets vérifiés", flush=True)
    (root/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
