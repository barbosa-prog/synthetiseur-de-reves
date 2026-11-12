"""Un seul pipeline/job GPU, local et privé ; aucun prompt dans stdout ou arguments."""

import io
import json
import sys
import time
from pathlib import Path

from common import paths, ram_mib
from cpu_mini import emit


def main():
    if sys.stdin.buffer.readline(32).rstrip(b"\r\n") != b"CPU_ONLY":
        return 1
    directory = Path(sys.argv[-1]).resolve()
    assert directory.parent == paths()[0] and directory.name.startswith("private-image-")
    payload = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    import torch
    from diffusers import StableDiffusionPipeline
    emit("imports_ready", seconds=round(time.perf_counter()-started, 6))
    begin = time.perf_counter()
    pipeline = StableDiffusionPipeline.from_pretrained(
        payload["model_path"], torch_dtype=torch.float16, variant="fp16",
        use_safetensors=True, local_files_only=True, low_cpu_mem_usage=True, device_map="cuda",
    )
    torch.cuda.synchronize()
    emit("after_pipeline_load", seconds=round(time.perf_counter()-begin, 6), weights_loaded=True)
    assert pipeline.safety_checker is not None and pipeline.feature_extractor is not None
    for name in ("unet", "vae", "text_encoder", "safety_checker"):
        assert all(p.device.type == "cuda" and p.dtype == torch.float16
                   for p in getattr(pipeline, name).parameters())
    free, _ = torch.cuda.mem_get_info()
    if ram_mib() < 2048 or free < 1536*1024**2:
        emit("memory_refused")
        return 1
    emit("before_inference", steps=20, seed=payload["seed"], width=512, height=512)
    begin = time.perf_counter()
    with torch.inference_mode():
        result = pipeline(payload["description"], width=512, height=512, num_inference_steps=20,
                          num_images_per_prompt=1, generator=torch.Generator(device="cuda")
                          .manual_seed(payload["seed"]), output_type="pil")
    torch.cuda.synchronize()
    emit("after_inference", seconds=round(time.perf_counter()-begin, 6))
    assert result.nsfw_content_detected is not None and len(result.images) == 1
    assert len(result.nsfw_content_detected) == 1
    blocked = bool(result.nsfw_content_detected[0])
    if not blocked:
        assert result.images[0].size == (512, 512)
        output = io.BytesIO()
        result.images[0].save(output, format="PNG")
        assert 0 < output.tell() <= 8*1024**2
        (directory / "output.png").write_bytes(output.getvalue())
    emit("application_image_finished", blocked=blocked)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Pas de traceback d'exception Python pouvant contenir la description privée.
        torch_module = sys.modules.get("torch")
        if torch_module is not None and isinstance(exc, torch_module.OutOfMemoryError):
            emit("memory_refused")
        else:
            emit("application_image_failed")
        raise SystemExit(1) from None
