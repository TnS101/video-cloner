from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_LAMA_ROI_PROOF_V1"
MODEL_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
MODEL_SHA256 = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
EXPECTED_TORCH_PREFIX = "2.8.0+cu128"
MIN_GPU_MEMORY_MIB = 11000
CHUNK_BYTES = 4 * 1024 * 1024


class ProvisionError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProvisionError(f"repository root not found: {root}")
    return root


def default_external_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ProvisionError("LOCALAPPDATA is required")
    return Path(local) / "VideoCloner" / "lama_roi_proof_v1"


def proven_runtime_python() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ProvisionError("LOCALAPPDATA is required")
    python = Path(local) / "VideoCloner" / "diffueraser_proof_v1" / "venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise ProvisionError(f"proven DiffuEraser CUDA runtime is missing: {python}")
    return python


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(value) for value in args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode != 0:
        raise ProvisionError(
            f"command failed ({result.returncode}): {' '.join(map(str, args))}\n{(result.stdout or '')[-8000:]}"
        )
    return result


def probe_runtime(python: Path) -> dict[str, object]:
    helper = r'''
import json, torch, cv2, numpy, PIL
payload = {
    "python": __import__("sys").version,
    "torch": torch.__version__,
    "cuda_runtime": torch.version.cuda,
    "cuda_available": bool(torch.cuda.is_available()),
    "device_count": int(torch.cuda.device_count()),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "device_memory_mib": int(torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)) if torch.cuda.is_available() else 0,
    "opencv": cv2.__version__,
    "numpy": numpy.__version__,
    "pillow": PIL.__version__,
}
print(json.dumps(payload, sort_keys=True))
'''
    result = run([str(python), "-c", helper])
    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        raise ProvisionError("CUDA runtime probe produced no JSON")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"invalid CUDA runtime probe output: {lines[-1]}") from exc
    if payload.get("cuda_available") is not True:
        raise ProvisionError("CUDA is not available in the proven DiffuEraser runtime")
    if not str(payload.get("torch", "")).startswith(EXPECTED_TORCH_PREFIX):
        raise ProvisionError(f"unexpected torch runtime: {payload.get('torch')}")
    if int(payload.get("device_memory_mib", 0)) < MIN_GPU_MEMORY_MIB:
        raise ProvisionError(f"GPU memory below proof floor: {payload.get('device_memory_mib')} MiB")
    return payload


def _download_once(url: str, partial: Path) -> tuple[int, bool]:
    start = partial.stat().st_size if partial.is_file() else 0
    headers = {"User-Agent": "VideoCloner-LaMa-Proof/1"}
    if start:
        headers["Range"] = f"bytes={start}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        status = int(getattr(response, "status", response.getcode()))
        resumed = bool(start and status == 206)
        if start and not resumed:
            start = 0
            partial.unlink(missing_ok=True)
        mode = "ab" if resumed else "wb"
        with partial.open(mode) as handle:
            while True:
                block = response.read(CHUNK_BYTES)
                if not block:
                    break
                handle.write(block)
    return partial.stat().st_size, resumed


def ensure_model(model_path: Path) -> dict[str, object]:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.is_file():
        actual = sha256_file(model_path)
        if actual == MODEL_SHA256:
            return {
                "path": str(model_path),
                "sha256": actual,
                "downloaded": False,
                "resumed": False,
                "bytes": model_path.stat().st_size,
            }
        mismatch = model_path.with_name(f"{model_path.name}.sha_mismatch_{actual[:12]}")
        if mismatch.exists():
            mismatch.unlink()
        model_path.replace(mismatch)

    quarantine_pattern = f"{model_path.name}*.sha_mismatch_*"
    for candidate in sorted(model_path.parent.glob(quarantine_pattern)):
        if not candidate.is_file():
            continue
        actual = sha256_file(candidate)
        if actual != MODEL_SHA256:
            continue
        os.replace(candidate, model_path)
        return {
            "path": str(model_path),
            "sha256": actual,
            "downloaded": False,
            "resumed": False,
            "reused_quarantined_download": True,
            "source_path": str(candidate),
            "bytes": model_path.stat().st_size,
        }

    partial = model_path.with_suffix(model_path.suffix + ".part")
    last_error: Exception | None = None
    resumed_any = False
    for attempt in range(1, 4):
        try:
            _, resumed = _download_once(MODEL_URL, partial)
            resumed_any = resumed_any or resumed
            actual = sha256_file(partial)
            if actual != MODEL_SHA256:
                mismatch = partial.with_name(f"{partial.name}.sha_mismatch_{actual[:12]}")
                if mismatch.exists():
                    mismatch.unlink()
                partial.replace(mismatch)
                raise ProvisionError(
                    f"LaMa model SHA-256 mismatch: expected {MODEL_SHA256}, got {actual}"
                )
            os.replace(partial, model_path)
            return {
                "path": str(model_path),
                "sha256": actual,
                "downloaded": True,
                "resumed": resumed_any,
                "bytes": model_path.stat().st_size,
                "attempt": attempt,
            }
        except (OSError, urllib.error.URLError, ProvisionError) as exc:
            last_error = exc
            if isinstance(exc, ProvisionError) and "SHA-256 mismatch" in str(exc):
                break
    raise ProvisionError(f"LaMa model provisioning failed: {last_error}")


def model_load_probe(python: Path, model_path: Path) -> dict[str, object]:
    helper = r'''
import json, sys, torch
model_path = sys.argv[1]
device = torch.device("cuda:0")
model = torch.jit.load(model_path, map_location=device)
model.eval().to(device)
x = torch.zeros((1,3,64,64), device=device, dtype=torch.float32)
m = torch.zeros((1,1,64,64), device=device, dtype=torch.int64)
m[:,:,24:40,24:40] = 1
with torch.inference_mode():
    y = model(x, m)
torch.cuda.synchronize()
print(json.dumps({"shape": list(y.shape), "dtype": str(y.dtype), "device": str(y.device)}))
'''
    result = run([str(python), "-c", helper, str(model_path)])
    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        raise ProvisionError("LaMa load/inference probe produced no JSON")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"invalid LaMa model probe output: {lines[-1]}") from exc
    if payload.get("shape") != [1, 3, 64, 64] or payload.get("device") != "cuda:0":
        raise ProvisionError(f"unexpected LaMa probe result: {payload}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--report", required=True)
    parser.add_argument("--external-root")
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    external_root = Path(args.external_root).resolve() if args.external_root else default_external_root()
    python = proven_runtime_python()
    runtime = probe_runtime(python)
    model = ensure_model(external_root / "big-lama.pt")
    load_probe = model_load_probe(python, Path(model["path"]))
    report = {
        "task_id": TASK_ID,
        "ok": True,
        "repo_root": str(repo_root),
        "python": str(python),
        "external_root": str(external_root),
        "model_url": MODEL_URL,
        "model": model,
        "runtime": runtime,
        "model_probe": load_probe,
        "runtime_reused_from": "diffueraser_proof_v1_cuda_venv",
        "production_inference_executed": False,
        "resolve_invocations": 0,
    }
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"task_id": TASK_ID, "status": "provisioned", "python": str(python), "model": model["path"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
