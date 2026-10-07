param(
    [Parameter(Mandatory=$true)][string]$PlanId,
    [string]$RepoRoot = ".",
    [string]$LatestReport = ""
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path $RepoRoot).Path
Set-Location $root

Write-Host "GitHub main is the preferred Browser Architect context. This script is fallback only." -ForegroundColor Yellow

$files = @(
    "ARCHITECT_RULES.md",
    "PROJECT_STATE.md",
    "ARCHITECTURE.md",
    "PROJECT_TRACKER.xlsx",
    "plan.md"
)

foreach ($f in $files) {
    if (-not (Test-Path $f)) { throw "Missing mandatory browser-context file: $f" }
}

$handoffRoot = Join-Path $root ".handoffs"
$staging = Join-Path $handoffRoot ("{0}_browser_context" -f $PlanId)
$zip = Join-Path $handoffRoot ("{0}_browser_context.zip" -f $PlanId)

if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging -Force | Out-Null
foreach ($f in $files) { Copy-Item $f -Destination $staging }

if ($LatestReport) {
    if (-not (Test-Path $LatestReport)) { throw "LatestReport not found: $LatestReport" }
    Copy-Item $LatestReport -Destination (Join-Path $staging "LATEST_REPORT.md")
}

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $staging -Recurse -Force

Write-Host "Created fallback context: $zip" -ForegroundColor Green
