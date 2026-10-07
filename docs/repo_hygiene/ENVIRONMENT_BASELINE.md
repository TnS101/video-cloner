# Environment Baseline

Captured read-only on 2026-10-07 for the current canonical route. This records the machine that produced the baseline; it is not the final dependency specification.

## Platform and executables

| Role | Version / path |
| --- | --- |
| OS | Windows 11, `10.0.26200`, AMD64 |
| Canonical regression Python | CPython 3.14.5 — `C:\Python314\python.exe` |
| Default analyzer Python | CPython 3.14.5 — `Virtual Environments\venv\Scripts\python.exe` |
| Audio analyzer Python | CPython 3.10.11 — `Virtual Environments\venv_audio\Scripts\python.exe` |
| OCR analyzer Python | CPython 3.10.11 — `Virtual Environments\venv_ocr\Scripts\python.exe` |
| ffmpeg | `2026-05-25-git-34dfa8bf2b-essentials_build-www.gyan.dev` — `C:\ffmpeg\bin\ffmpeg.exe` |
| yt-dlp | `2026.08.30.232658` — `C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\Scripts\yt-dlp.exe` |
| Ollama | `0.35.1`; service reachable; local `llama3.1:latest` (`46e0c10c039e`, 4.9 GB) present |
| GPU | NVIDIA GeForce RTX 5070, driver 596.36, 12227 MiB, compute capability 12.0 |
| DaVinci Resolve | 21.0.1.11 portable executable at `C:\Users\User\Downloads\DaVinci Resolve Studio 21.0.1.11 Portable 7997\Blackmagic Design DaVinci Resolve Studio 21.0.1 BUILD 11 x64 x64 Multi-Ru Portable by 7997\Resolve\App\DaVinci Resolve\Resolve.exe`; scripting module found under ProgramData |

Interpreter locations are current-machine facts and must become configurable inputs, not committed defaults. The cookies environment value was deliberately not recorded.

## Canonical imported dependencies

The current source path imports standard library modules plus these external capabilities:

| Runtime role | Relevant installed packages |
| --- | --- |
| Regression | pytest 9.1.1; NumPy 2.4.4; opencv-contrib-python 4.13.0.92 |
| Default analysis | NumPy 2.4.6; opencv-python 4.13.0.92; PySceneDetect (`scenedetect`) 0.7 |
| Audio | faster-whisper 1.2.1; CTranslate2 4.8.0; librosa 0.10.1; NumPy 1.23.5; nvidia-cublas-cu12 12.9.2.10; nvidia-cudnn-cu12 9.23.1.3 |
| OCR / segmentation | PaddleOCR 2.7.3; PaddlePaddle GPU distribution `3.0.0.dev20250717` (runtime 3.0.0); PaddleHub 2.4.0; NumPy 1.23.5; OpenCV packages 4.6.0.66 |
| Planning | Python standard-library HTTP client; Ollama is used only when `plan_edit.py` is invoked without `--llm-response` |
| Resolve | `DaVinciResolveScript` supplied by the Resolve installation, not pip |

CUDA probes reported one CTranslate2 CUDA device. Paddle reported CUDA compilation enabled and selected `gpu:0`.

## Dependency-definition gap

No project-owned `pyproject.toml`, `requirements*.txt`, Python lock file, Pipfile, or Conda environment file exists outside ignored local virtual environments. The current route therefore depends on three differently provisioned Python interpreters plus external executables. Step 3 must create the canonical dependency declaration after package boundaries are established; this task does not guess or freeze a final solver output.

The machine-readable companion is `ENVIRONMENT_BASELINE.json`.
