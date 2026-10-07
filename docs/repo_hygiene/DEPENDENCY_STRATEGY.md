# Dependency Strategy

`pyproject.toml` installs the standard-library application core on CPython 3.10–3.14. Optional groups document capability interfaces; they are not a claim that OCR, audio, and core analysis safely share one environment.

| Worker | Evidence-backed environment | Bootstrap |
| --- | --- | --- |
| core/test | Python 3.14 | `python -m pip install -e ".[test,default-analysis]"` |
| audio | Python 3.10 | `python -m pip install -e ".[audio]"`; provision matching CUDA libraries separately when GPU is selected |
| OCR | Python 3.10 | `python -m pip install -e ".[ocr]"`; install the platform/CUDA-appropriate PaddlePaddle build separately |

PaddlePaddle GPU is deliberately not pinned as a universal project dependency because the accepted machine uses a specially provisioned development build. DaVinci Resolve and `DaVinciResolveScript` are external runtime integrations and are not package installation dependencies. ffmpeg, yt-dlp, Ollama, and Resolve executable locations belong to `RuntimeConfig`.
