"""Contrôle sans installation ni téléchargement ; --runtime après autorisation seulement."""

import argparse
import json
import sys
from pathlib import Path

from common import (
    PINS,
    QualificationError,
    free_disk_gib,
    gpu_info,
    paths,
    ram_mib,
    require_environment,
    versions,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", action="store_true", help="Tester CUDA dans le venv séparé")
    args = parser.parse_args()
    info = {"python": sys.version.split()[0],
            "isolated_venv": Path(sys.prefix).resolve() == paths()[1],
            "ram_available_mib": ram_mib(), "gpu": gpu_info(), "disk_free_gib": free_disk_gib(),
            "installed_versions": versions(), "proposed_versions": PINS,
            "runtime_validated": False}
    if args.runtime:
        require_environment()
        import torch
        if torch.version.cuda != "11.8" or not torch.cuda.is_available():
            raise QualificationError("Runtime CUDA 11.8 indisponible.")
        sample = torch.ones(1, device="cuda", dtype=torch.float16)
        torch.cuda.synchronize()
        info.update(runtime_validated=True, torch_cuda=torch.version.cuda,
                    compute_capability=list(torch.cuda.get_device_capability(0)),
                    fp16_cuda_operation_ok=sample.item() == 1)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = str(exc) if isinstance(exc, QualificationError) else type(exc).__name__
        print(f"Précontrôle arrêté : {detail}")
        raise SystemExit(1) from None
