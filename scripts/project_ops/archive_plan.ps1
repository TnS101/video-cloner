param(
    [Parameter(Mandatory=$true)][string]$PlanId,
    [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $RepoRoot).Path
Set-Location $root

if (-not (Test-Path "plan.md")) { throw "plan.md not found" }

$archiveDir = "docs/plans/archive"
New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
$dest = Join-Path $archiveDir ("{0}.md" -f $PlanId)

if (Test-Path $dest) { throw "Refusing to overwrite existing archived plan: $dest" }

$content = Get-Content "plan.md" -Raw
if ($content -notmatch [regex]::Escape($PlanId)) {
    throw "Plan ID '$PlanId' was not found inside plan.md. Refusing archive."
}

Copy-Item "plan.md" $dest
Write-Host "Archived current plan to $dest" -ForegroundColor Green
Write-Host "Now synchronize PROJECT_STATE.md + PROJECT_TRACKER.xlsx before creating the next Plan." -ForegroundColor Cyan
