from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

TASK_ID = "DZSQH7AUHJT_BAKED_CAPTION_DIFFUERASER_ROI_PROOF_V1"
DIFFUERASER_REPOSITORY = "https://github.com/lixiaowen-xw/DiffuEraser.git"
DIFFUERASER_COMMIT = "8e6f279ac7531e27ad1849c6f8dab5372a8597e7"
DIFFUERASER_REQUIRED_PATHS = (
    "run_diffueraser.py",
    "requirements.txt",
    "diffueraser/diffueraser.py",
    "diffueraser/pipeline_diffueraser.py",
    "propainter/inference.py",
    "libs",
)
TORCH_VERSION = "2.8.0"
TORCHVISION_VERSION = "0.23.0"
TORCH_INDEX_URL = "https://download.pytorch.org/whl/cu128"
NUMPY_VERSION = "1.26.4"
MIN_GPU_MEMORY_MIB = 11000

HF_MODELS = {
    "diffuEraser": {
        "repo_id": "lixiaowen/diffuEraser",
        "revision": "ad510dca07fa8e155d4bd8d002085bb8ec8f60e5",
        "allow_patterns": ["brushnet/**", "unet_main/**"],
    },
    "stable-diffusion-v1-5": {
        "repo_id": "stable-diffusion-v1-5/stable-diffusion-v1-5",
        "revision": "f03de327dd89b501a01da37fc5240cf4fdba85a1",
        "allow_patterns": [
            "model_index.json",
            "feature_extractor/**",
            "safety_checker/**",
            "scheduler/**",
            "text_encoder/**",
            "tokenizer/**",
        ],
    },
    "PCM_Weights": {
        "repo_id": "wangfuyun/PCM_Weights",
        "revision": "39560fead4ce00f94db3cb8e93dd8fba90ec0be6",
        "allow_patterns": ["sd15/pcm_sd15_smallcfg_2step_converted.safetensors"],
    },
    "sd-vae-ft-mse": {
        "repo_id": "stabilityai/sd-vae-ft-mse",
        "revision": "651c6dc459a3ae175a511e7086a28d7e8182ac0c",
        "allow_patterns": ["config.json", "diffusion_pytorch_model.*"],
    },
}

PROPAINTER_COMMIT = "e870e79321c31b733e2031af5aa2fb1fe3ac7eec"
PROPAINTER_REQUIRED_WEIGHTS = (
    "ProPainter.pth",
    "raft-things.pth",
    "recurrent_flow_completion.pth",
)


class ProvisionError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [str(value) for value in args],
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if check and result.returncode != 0:
        output = result.stdout or ""
        raise ProvisionError(f"command failed ({result.returncode}): {' '.join(map(str, args))}\n{output[-8000:]}")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_repo_root(value: str | None) -> Path:
    root = Path(value).resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        raise ProvisionError(f"repository root not found: {root}")
    return root


def default_external_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "VideoCloner" / "diffueraser_proof_v1"
    return Path.home() / "AppData" / "Local" / "VideoCloner" / "diffueraser_proof_v1"


def python_candidates() -> Iterable[list[str]]:
    launcher = shutil.which("py")
    if launcher:
        for version in ("3.10", "3.11"):
            yield [launcher, f"-{version}"]
    current = Path(sys.executable)
    if current.is_file() and sys.version_info[:2] in {(3, 10), (3, 11)}:
        yield [str(current)]


def find_bootstrap_python() -> list[str]:
    for candidate in python_candidates():
        probe = run(candidate + ["-c", "import sys; print(sys.version_info[:2])"], check=False)
        if probe.returncode == 0:
            return candidate
    raise ProvisionError("Python 3.10 or 3.11 is required for the isolated DiffuEraser proof runtime")


def venv_python(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe"


def ensure_venv(venv: Path) -> Path:
    python = venv_python(venv)
    if python.is_file():
        return python
    venv.parent.mkdir(parents=True, exist_ok=True)
    run(find_bootstrap_python() + ["-m", "venv", str(venv)])
    if not python.is_file():
        raise ProvisionError(f"venv creation did not produce {python}")
    return python


def current_git_commit(source: Path) -> str | None:
    if not (source / ".git").is_dir():
        return None
    result = run(["git", "rev-parse", "HEAD"], cwd=source, check=False)
    return (result.stdout or "").strip() if result.returncode == 0 else None


def source_path(external_root: Path) -> Path:
    return external_root / f"DiffuEraser_checkout_{DIFFUERASER_COMMIT[:12]}"


def ensure_source(source: Path) -> None:
    if shutil.which("git") is None:
        raise ProvisionError("git is required to provision DiffuEraser")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", "--no-tags", DIFFUERASER_REPOSITORY, str(source)])
    elif not (source / ".git").is_dir():
        raise ProvisionError(f"DiffuEraser source exists but is not a git clone: {source}")
    if current_git_commit(source) != DIFFUERASER_COMMIT:
        run(["git", "fetch", "--depth", "1", "origin", DIFFUERASER_COMMIT], cwd=source)
        run(["git", "checkout", "--detach", "--force", DIFFUERASER_COMMIT], cwd=source)
    actual = current_git_commit(source)
    if actual != DIFFUERASER_COMMIT:
        raise ProvisionError(f"DiffuEraser commit mismatch: expected {DIFFUERASER_COMMIT}, got {actual}")
    missing = [rel for rel in DIFFUERASER_REQUIRED_PATHS if not (source / rel).exists()]
    if missing:
        raise ProvisionError("DiffuEraser checkout missing required paths: " + ", ".join(missing))


def install_runtime(python: Path, external_root: Path) -> None:
    marker = external_root / "runtime_versions.json"
    expected = {
        "torch": TORCH_VERSION,
        "torchvision": TORCHVISION_VERSION,
        "numpy": NUMPY_VERSION,
        "diffusers": "0.29.2",
        "transformers": "4.41.1",
    }
    if marker.is_file():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        if existing == expected:
            probe = run(
                [str(python), "-c", "import torch,torchvision,diffusers,transformers,numpy,av,cv2; print(torch.__version__)"],
                check=False,
            )
            if probe.returncode == 0:
                return

    run([str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([
        str(python), "-m", "pip", "install",
        f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}", f"torchaudio=={TORCH_VERSION}",
        "--index-url", TORCH_INDEX_URL,
    ])
    deps = [
        "diffusers==0.29.2",
        "accelerate==0.25.0",
        "opencv-python==4.9.0.80",
        "imageio==2.34.1",
        "imageio-ffmpeg==0.5.1",
        "matplotlib",
        "transformers==4.41.1",
        "einops==0.8.0",
        "datasets==2.19.1",
        f"numpy=={NUMPY_VERSION}",
        "pillow==10.4.0",
        "tqdm==4.66.4",
        "urllib3==2.2.2",
        "zipp==3.19.2",
        "peft==0.13.2",
        "scipy==1.13.1",
        "av==14.0.1",
        "safetensors>=0.4.3",
        "huggingface_hub==0.25.2",
    ]
    run([str(python), "-m", "pip", "install"] + deps)
    run([str(python), "-m", "pip", "check"])
    marker.write_text(json.dumps(expected, indent=2, sort_keys=True), encoding="utf-8")


def download_models(python: Path, source: Path) -> list[dict[str, object]]:
    weights_root = source / "weights"
    weights_root.mkdir(parents=True, exist_ok=True)
    spec_path = weights_root / "video_cloner_hf_model_spec.json"
    spec_path.write_text(json.dumps(HF_MODELS, indent=2, sort_keys=True), encoding="utf-8")
    helper = r'''
import json, sys
from pathlib import Path
from huggingface_hub import snapshot_download, model_info
spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
root = Path(sys.argv[2])
rows=[]
for name, row in spec.items():
    info = model_info(row["repo_id"], revision=row["revision"])
    if info.sha != row["revision"]:
        raise RuntimeError(f"revision mismatch for {row['repo_id']}: {info.sha}")
    dest = root / name
    revision_marker = dest / ".video_cloner_revision"
    # An absent marker means a prior pinned snapshot_download was interrupted.
    # Keep that directory so Hugging Face can resume its .incomplete files on
    # Windows; only remove content that is explicitly marked as another revision.
    if dest.exists() and revision_marker.is_file() and revision_marker.read_text(encoding="utf-8").strip() != row["revision"]:
        import shutil
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=row["repo_id"],
        revision=row["revision"],
        local_dir=str(dest),
        local_dir_use_symlinks=False,
        allow_patterns=row["allow_patterns"],
        resume_download=True,
    )
    revision_marker.write_text(row["revision"], encoding="utf-8")
    rows.append({"name":name,"repo_id":row["repo_id"],"revision":row["revision"],"path":str(dest)})
print(json.dumps(rows))
'''
    result = run([str(python), "-c", helper, str(spec_path), str(weights_root)])
    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        raise ProvisionError("Hugging Face model download produced no result")
    try:
        rows = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ProvisionError(f"invalid Hugging Face download result: {lines[-1]}") from exc
    return rows


def copy_propainter_weights(source: Path) -> list[dict[str, object]]:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise ProvisionError("LOCALAPPDATA is required to reuse the proven ProPainter weights")
    proven_source = Path(local) / "VideoCloner" / "propainter_proof_v1" / f"ProPainter_checkout_{PROPAINTER_COMMIT[:12]}" / "weights"
    target = source / "weights" / "propainter"
    target.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in PROPAINTER_REQUIRED_WEIGHTS:
        src = proven_source / name
        dst = target / name
        if not src.is_file() or src.stat().st_size <= 0:
            raise ProvisionError(f"proven ProPainter weight is missing: {src}")
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size or sha256_file(dst) != sha256_file(src):
            shutil.copy2(src, dst)
        rows.append({"name": name, "bytes": dst.stat().st_size, "sha256": sha256_file(dst)})
    return rows


def verify_model_layout(source: Path) -> None:
    required = [
        source / "weights" / "diffuEraser" / "brushnet" / "config.json",
        source / "weights" / "diffuEraser" / "unet_main" / "config.json",
        source / "weights" / "stable-diffusion-v1-5" / "model_index.json",
        source / "weights" / "stable-diffusion-v1-5" / "scheduler" / "scheduler_config.json",
        source / "weights" / "stable-diffusion-v1-5" / "text_encoder" / "config.json",
        source / "weights" / "stable-diffusion-v1-5" / "tokenizer" / "tokenizer_config.json",
        source / "weights" / "PCM_Weights" / "sd15" / "pcm_sd15_smallcfg_2step_converted.safetensors",
        source / "weights" / "sd-vae-ft-mse" / "config.json",
    ]
    vae_root = source / "weights" / "sd-vae-ft-mse"
    if not any((vae_root / name).is_file() for name in ("diffusion_pytorch_model.safetensors", "diffusion_pytorch_model.bin")):
        required.append(vae_root / "diffusion_pytorch_model.safetensors|bin")
    for name in PROPAINTER_REQUIRED_WEIGHTS:
        required.append(source / "weights" / "propainter" / name)
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size <= 0]
    if missing:
        raise ProvisionError("model layout incomplete: " + "; ".join(missing))


def gpu_probe(python: Path, source: Path) -> dict[str, object]:
    code = r'''
import json, torch, torchvision, diffusers, transformers, cv2, av
payload={
 "torch":torch.__version__, "torchvision":torchvision.__version__,
 "torch_cuda":torch.version.cuda, "diffusers":diffusers.__version__,
 "transformers":transformers.__version__, "cuda_available":bool(torch.cuda.is_available()),
}
if torch.cuda.is_available():
    props=torch.cuda.get_device_properties(0)
    payload.update({"device_name":props.name,"device_capability":list(torch.cuda.get_device_capability(0)),"memory_total_mib":int(props.total_memory//(1024*1024))})
    a=torch.randn((64,64),device="cuda"); b=a@a; torch.cuda.synchronize(); payload["cuda_kernel_smoke"]=float(b.abs().mean().item())
print(json.dumps(payload))
'''
    result = run([str(python), "-c", code], cwd=source)
    lines = (result.stdout or "").strip().splitlines()
    if not lines:
        raise ProvisionError("GPU probe produced no output")
    payload = json.loads(lines[-1])
    if not payload.get("cuda_available"):
        raise ProvisionError("DiffuEraser proof requires CUDA")
    if int(payload.get("memory_total_mib", 0)) < MIN_GPU_MEMORY_MIB:
        raise ProvisionError(
            f"DiffuEraser ROI proof requires at least {MIN_GPU_MEMORY_MIB} MiB total VRAM; got {payload.get('memory_total_mib')} MiB"
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root")
    parser.add_argument("--external-root")
    parser.add_argument("--report-json", required=True)
    args = parser.parse_args()

    resolve_repo_root(args.repo_root)
    external_root = Path(args.external_root).resolve() if args.external_root else default_external_root()
    external_root.mkdir(parents=True, exist_ok=True)
    source = source_path(external_root)
    venv = external_root / "venv"
    python = ensure_venv(venv)
    ensure_source(source)
    install_runtime(python, external_root)
    model_rows = download_models(python, source)
    propainter_rows = copy_propainter_weights(source)
    verify_model_layout(source)
    probe = gpu_probe(python, source)

    report = {
        "task_id": TASK_ID,
        "ok": True,
        "source": str(source),
        "source_commit": current_git_commit(source),
        "python": str(python),
        "venv": str(venv),
        "gpu": probe,
        "hf_models": model_rows,
        "propainter_weights": propainter_rows,
        "min_gpu_memory_mib": MIN_GPU_MEMORY_MIB,
    }
    report_path = Path(args.report_json).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
