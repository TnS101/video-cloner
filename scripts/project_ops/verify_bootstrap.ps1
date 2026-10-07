param([string]$RepoRoot = ".")

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $RepoRoot).Path
Set-Location $root

$required = @(
    "AGENTS.md",
    "ARCHITECT_RULES.md",
    "PROJECT_STATE.md",
    "ARCHITECTURE.md",
    "plan.md",
    "PROJECT_TRACKER.xlsx",
    "docs/RESEARCH_BASELINE.md",
    "docs/DECISIONS.md",
    "docs/TEST_STRATEGY.md",
    ".project_ops/templates/REPORT_TEMPLATE.md",
    ".project_ops/config.json"
)

Write-Host "=== VIDEO CLONER PROJECT OPS PREFLIGHT ===" -ForegroundColor Cyan
Write-Host "Root: $root"

$missing = @()
foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        $missing += $path
        Write-Host "MISSING  $path" -ForegroundColor Red
    } else {
        Write-Host "OK       $path" -ForegroundColor Green
    }
}

Write-Host "`n=== GIT ===" -ForegroundColor Cyan
if (-not (Test-Path ".git")) {
    Write-Host "BLOCKED: .git directory not found." -ForegroundColor Red
    exit 2
}

git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short

Write-Host "`n=== NAMESPACE CHECK ===" -ForegroundColor Cyan
if (-not (Test-Path ".agent/README.md")) {
    Write-Host "WARNING: .agent/README.md missing; verify Resolve runtime boundary." -ForegroundColor Yellow
} else {
    Write-Host "OK       .agent remains Resolve runtime namespace" -ForegroundColor Green
}

if ($missing.Count -gt 0) {
    Write-Host "`nRESULT: BLOCKED_MISSING_PROJECT_OPS_FILES" -ForegroundColor Red
    exit 2
}

Write-Host "`nRESULT: PROJECT_OPS_FILE_GATES_PRESENT" -ForegroundColor Green
Write-Host "NOTE: External/global skills are checked by Codex only when applicable; they are not a universal blocker." -ForegroundColor Cyan
