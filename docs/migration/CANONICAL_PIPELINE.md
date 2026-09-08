# Canonical Video Cloner Pipeline

1. Input: URL or local video.
2. Run context: deterministic video identity, roots, artifact paths, and sanitized runtime metadata.
3. Source acquisition: yt-dlp for URL inputs; validated existing path for local inputs.
4. Media preparation: source produces WAV and proxy.
5. Standalone analysis orchestration: canonical analyzers remain independently callable; the runner validates non-empty prerequisites, executes a fixed DAG, validates JSON outputs, and reuses only hash-matched outputs.
   - WAV -> transcript and rhythm.
   - Proxy -> cuts/shots.
   - Source video + transcript -> caption style.
   - Proxy + shots -> motion and transitions.
   - Proxy + caption style + transcript -> caption occlusion.
   Cache identity includes the analyzer script, actual configured interpreter, deterministic command profile, and required input hashes. Caption-occlusion reuse additionally fingerprints its primary JSON and all required foreground-mask manifests and frames; zero requested masks are a valid no-sidecar result, while optional debug/audit artifacts are excluded.
6. Planning: merge, plan, validate, and compile generic source-preserving operations. Not implemented by Phase 2.
7. Compilation: OTIO, SRT, and Text+ timeline artifacts.
8. Resolve application: permanent bridge only.
9. Verification: persistent readback, idempotency, regression, immutable artifacts, and visual approval where required.

Phases 1 and 2 implement stages 1-5. Analysis produces observations only. Existing n8n remains immutable orchestration evidence; its analysis-node responsibilities are superseded only after Phase 2 acceptance.
