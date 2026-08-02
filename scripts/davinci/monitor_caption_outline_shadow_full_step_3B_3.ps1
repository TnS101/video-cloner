param(
    [string]$StatusPath = 'C:\Users\User\Downloads\Projects\Video Cloner\data\DZsqH7auhjt\davinci\DZsqH7auhjt_resolve_outline_shadow_full_step_3B_3B_workspace_status.json'
)

Write-Host 'Monitoring Step 3B.3B. Press Ctrl+C to stop monitoring only.'
Write-Host 'This does not stop the Resolve Workspace script.'
Start-Sleep -Seconds 1

while ($true) {
    Clear-Host
    Write-Host 'Video Cloner - Step 3B.3B live status'
    Write-Host ('Time: ' + (Get-Date))
    Write-Host ''

    if (Test-Path -LiteralPath $StatusPath) {
        try {
            $j = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json
            Write-Host ('Running: ' + $j.running)
            Write-Host ('Version: ' + $j.version)
            Write-Host ('Run ID: ' + $j.run_id)
            Write-Host ('Stage: ' + $j.stage)

            if ($null -ne $j.progress) {
                $current = if ($null -ne $j.progress.current) { $j.progress.current } else { '-' }
                $total = if ($null -ne $j.progress.total) { $j.progress.total } else { '-' }
                $percent = if ($null -ne $j.progress.percent) { $j.progress.percent } else { '-' }
                Write-Host ('Progress: ' + $current + '/' + $total + ' (' + $percent + '%)')
                Write-Host ('Item: ' + $j.progress.item)
                Write-Host ('Message: ' + $j.progress.message)
            }

            Write-Host ('Elapsed seconds: ' + $j.elapsed_seconds)
            if ($null -ne $j.failures) {
                Write-Host ('Failures: ' + ($j.failures -join ', '))
            }

            if ($j.running -eq $false) {
                Write-Host ''
                Write-Host 'Run finished. Review the completion dialog and report.'
                break
            }
        }
        catch {
            Write-Host ('Status parse error: ' + $_.Exception.Message)
        }
    }
    else {
        Write-Host 'Waiting for Workspace status file...'
    }

    Start-Sleep -Seconds 2
}
