param(
    [string]$StatusPath = 'C:\Users\User\Downloads\Projects\Video Cloner\data\DZsqH7auhjt\davinci\DZsqH7auhjt_resolve_source_geometry_step_3B_6C_workspace_status.json'
)
Write-Host 'Monitoring Step 3B.6C. Press Ctrl+C to stop monitoring only.'
while ($true) {
    Clear-Host
    Write-Host 'Video Cloner - Step 3B.6C source geometry probe'
    Write-Host ('Time: ' + (Get-Date)); Write-Host ''
    if (Test-Path -LiteralPath $StatusPath) {
        try {
            $j = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json
            Write-Host ('Running: ' + $j.running)
            Write-Host ('Version: ' + $j.version)
            Write-Host ('Run ID: ' + $j.run_id)
            Write-Host ('Mode: ' + $j.run_mode)
            Write-Host ('Stage: ' + $j.stage)
            if ($null -ne $j.summary) {
                Write-Host ('Keys verified: ' + $j.summary.target_key_verified_count + '/' + $j.summary.target_key_count)
                Write-Host ('Other V3 preserved: ' + $j.summary.non_probe_caption_verified_count + '/' + $j.summary.non_probe_caption_count)
                Write-Host ('Failures: ' + $j.summary.failed_count)
            }
            if ($null -ne $j.failures -and $j.failures.Count -gt 0) { Write-Host ('Failure codes: ' + ($j.failures -join ', ')) }
            if ($j.running -eq $false) { Write-Host ''; Write-Host 'Run finished. Review the completion dialog and report.'; break }
        } catch { Write-Host ('Status parse error: ' + $_.Exception.Message) }
    } else { Write-Host 'Waiting for Workspace status file...' }
    Start-Sleep -Seconds 2
}
