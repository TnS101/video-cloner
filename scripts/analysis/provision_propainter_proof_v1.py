from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_VIDEO_INPAINT_PROOF_V9"
PROPAINTER_REPOSITORY = "https://github.com/sczhou/ProPainter.git"
PROPAINTER_COMMIT = "e870e79321c31b733e2031af5aa2fb1fe3ac7eec"
PROPAINTER_REQUIRED_PATHS = (
    "requirements.txt",
    "inference_propainter.py",
    "core",
    "model",
    "utils",
)
TORCH_VERSION = "2.8.0"
TORCHVISION_VERSION = "0.23.0"
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
NUMPY_VERSION = "1.26.4"


class ProvisionError(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(value) for value in args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if check and result.returncode != 0:
        output = result.stdout or ""
        raise ProvisionError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{output[-6000:]}"
        )
    return result


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProvisionError(f"repository root not found: {root}")
    return root


def default_external_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "VideoCloner" / "propainter_proof_v1"
    return Path.home() / "AppData" / "Local" / "VideoCloner" / "propainter_proof_v1"


def python_candidates() -> Iterable[list[str]]:
    launcher = shutil.which("py")
    if launcher:
        for version in ("3.10", "3.11", "3.12"):
            yield [launcher, f"-{version}"]
    current = Path(sys.executable)
    if current.is_file() and sys.version_info[:2] in {(3, 10), (3, 11), (3, 12)}:
        yield [str(current)]


def find_bootstrap_python() -> list[str]:
    seen: set[str] = set()
    for candidate in python_candidates():
        key = "\0".join(candidate)
        if key in seen:
            continue
        seen.add(key)
        probe = run(
            candidate + ["-c", "import sys; print(sys.executable); print(sys.version_info[:2])"],
            check=False,
        )
        if probe.returncode == 0:
            return candidate
    raise ProvisionError("Python 3.10, 3.11, or 3.12 is required for the isolated ProPainter proof runtime")


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe"


def ensure_venv(venv: Path) -> Path:
    python = venv_python(venv)
    if python.is_file():
        return python
    venv.parent.mkdir(parents=True, exist_ok=True)
    bootstrap = find_bootstrap_python()
    run(bootstrap + ["-m", "venv", str(venv)])
    if not python.is_file():
        raise ProvisionError(f"virtual environment creation did not produce {python}")
    return python


def current_propainter_commit(source: Path) -> str | None:
    if not (source / ".git").is_dir():
        return None
    result = run(["git", "rev-parse", "HEAD"], cwd=source, check=False)
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def missing_propainter_paths(source: Path) -> list[str]:
    return [name for name in PROPAINTER_REQUIRED_PATHS if not (source / name).exists()]


def propainter_source_path(external_root: Path) -> Path:
    # Provision-fix V1 used %LOCALAPPDATA%/.../ProPainter, which may contain an
    # empty --no-checkout worktree left by the failed first attempt. Do not reuse
    # or mutate that ambiguous directory. A commit-qualified path gives this proof
    # a fresh deterministic checkout while preserving the old evidence/cache.
    return external_root / f"ProPainter_checkout_{PROPAINTER_COMMIT[:12]}"


def ensure_propainter_source(source: Path) -> None:
    if shutil.which("git") is None:
        raise ProvisionError("git is required to provision ProPainter")

    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        # A normal clone must materialize the worktree. The previous two failures
        # both originated from reusing a --no-checkout clone, so this path
        # deliberately forbids --no-checkout. Blob filtering keeps network usage
        # bounded without changing checkout semantics.
        run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-tags",
                PROPAINTER_REPOSITORY,
                str(source),
            ]
        )
    elif not (source / ".git").is_dir():
        raise ProvisionError(f"external ProPainter source path exists but is not a git clone: {source}")

    actual_before = current_propainter_commit(source)
    if actual_before != PROPAINTER_COMMIT:
        run(["git", "fetch", "--depth", "1", "origin", PROPAINTER_COMMIT], cwd=source)
        run(
            [
                "git",
                "-c",
                "core.sparseCheckout=false",
                "checkout",
                "--detach",
                "--force",
                PROPAINTER_COMMIT,
            ],
            cwd=source,
        )

    actual = current_propainter_commit(source)
    if actual != PROPAINTER_COMMIT:
        raise ProvisionError(f"ProPainter commit mismatch: expected {PROPAINTER_COMMIT}, got {actual}")

    missing_after = missing_propainter_paths(source)
    if missing_after:
        raise ProvisionError(
            "fresh ProPainter checkout is incomplete: " + ", ".join(missing_after)
        )


def runtime_probe(python: Path, source: Path) -> dict[str, object]:
    code = r'''
import json
import sys
payload = {"python": sys.executable, "python_version": sys.version}
try:
    import torch
    import torchvision
    import cv2
    import numpy
    import scipy
    import skimage
    import timm
    import av
    payload.update({
        "ok": bool(torch.cuda.is_available()),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "torch_cuda": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "device_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
        "numpy": numpy.__version__,
        "opencv": cv2.__version__,
    })
    if torch.cuda.is_available():
        x = torch.randn((64, 64), device="cuda")
        y = x @ x
        torch.cuda.synchronize()
        payload["cuda_kernel_smoke"] = float(y.abs().mean().item())
        payload["ok"] = bool(payload["ok"] and payload["cuda_kernel_smoke"] >= 0.0)
except Exception as exc:
    payload.update({"ok": False, "error": repr(exc)})
print(json.dumps(payload))
'''
    result = run([str(python), "-c", code], cwd=source, check=False)
    text = (result.stdout or "").strip().splitlines()
    if result.returncode != 0 or not text:
        return {"ok": False, "error": (result.stdout or "runtime probe failed")[-4000:]}
    try:
        return json.loads(text[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": (result.stdout or "invalid runtime probe output")[-4000:]}


def install_runtime(python: Path, source: Path, external_root: Path) -> None:
    requirements = source / "requirements.txt"
    if not requirements.is_file():
        raise ProvisionError(f"ProPainter requirements file is missing after pinned checkout: {requirements}")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            f"torch=={TORCH_VERSION}",
            f"torchvision=={TORCHVISION_VERSION}",
            "--index-url",
            TORCH_INDEX_URL,
        ]
    )
    constraints = external_root / "constraints.txt"
    constraints.write_text(
        "\n".join(
            [
                f"numpy=={NUMPY_VERSION}",
                f"torch=={TORCH_VERSION}",
                f"torchvision=={TORCHVISION_VERSION}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run([str(python), "-m", "pip", "install", f"numpy=={NUMPY_VERSION}"])
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
            "-c",
            str(constraints),
        ],
        cwd=source,
    )


def verify_inference_api(python: Path, source: Path) -> str:
    script = source / "inference_propainter.py"
    if not script.is_file():
        raise ProvisionError(f"missing ProPainter inference script: {script}")
    text = script.read_text(encoding="utf-8")
    for needle in ("--subvideo_length", "--neighbor_length", "--ref_stride", "--fp16", "--save_frames"):
        if needle not in text:
            raise ProvisionError(f"pinned ProPainter source is missing required inference option: {needle}")
    result = run([str(python), str(script), "--help"], cwd=source, check=False)
    if result.returncode != 0:
        raise ProvisionError(f"ProPainter --help smoke test failed:\n{(result.stdout or '')[-6000:]}")
    return result.stdout or ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--external-root")
    args = parser.parse_args()

    repo_root = resolve_repo_root(args.repo_root)
    artifact_dir = Path(args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    external_root = Path(args.external_root).resolve() if args.external_root else default_external_root().resolve()
    venv = external_root / "venv"
    source = propainter_source_path(external_root)
    external_root.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "task_id": TASK_ID,
        "ok": False,
        "repository_root": str(repo_root),
        "external_root": str(external_root),
        "propainter_repository": PROPAINTER_REPOSITORY,
        "propainter_commit_expected": PROPAINTER_COMMIT,
        "torch_version_expected": TORCH_VERSION,
        "torchvision_version_expected": TORCHVISION_VERSION,
        "torch_index_url": TORCH_INDEX_URL,
    }
    output = artifact_dir / "PROPAINTER_TOOLCHAIN.json"
    pointer = artifact_dir / "propainter_python.txt"
    try:
        if shutil.which("nvidia-smi") is None:
            raise ProvisionError("nvidia-smi is required; GPU proof is not allowed to fall back to CPU")
        gpu_query = run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            check=True,
        )
        payload["nvidia_smi"] = (gpu_query.stdout or "").strip()
        python = ensure_venv(venv)
        ensure_propainter_source(source)
        probe = runtime_probe(python, source)
        if not probe.get("ok"):
            install_runtime(python, source, external_root)
            probe = runtime_probe(python, source)
        if not probe.get("ok"):
            raise ProvisionError(f"CUDA ProPainter runtime probe failed: {probe}")
        help_text = verify_inference_api(python, source)
        payload.update(
            {
                "ok": True,
                "python": str(python),
                "source": str(source),
                "propainter_commit_actual": current_propainter_commit(source),
                "runtime": probe,
                "required_inference_options_verified": True,
                "help_smoke_output_tail": help_text[-2000:],
            }
        )
        pointer.write_text(str(python) + "\n", encoding="utf-8")
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0
    except Exception as exc:
        payload["error"] = repr(exc)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
