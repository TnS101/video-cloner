param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$VideoId
)

$Status = Join-Path $ProjectRoot "data\$VideoId\davinci\${VideoId}_caption_word_instance_tracks_step_3B_6B_status.json"
Write-Host "Monitoring Major Step 3B.6B"
Write-Host "Status: $Status"
Write-Host "Press Ctrl+C to stop monitoring. The detector will keep running."
Write-Host ""

while ($true) {
    Clear-Host
    Write-Host "Video Cloner - Step 3B.6B dense re-detection"
    Write-Host ""
    if (Test-Path -LiteralPath $Status) {
        try {
            $j = Get-Content -LiteralPath $Status -Raw | ConvertFrom-Json
            Write-Host ("Running:       " + $j.running)
            Write-Host ("Stage:         " + $j.stage)
            Write-Host ("Scene:         " + $j.scene_id)
            Write-Host ("Scene progress:" + $j.scene_index + "/" + $j.scene_count)
            Write-Host ("Frame:         " + $j.current_frame + " / " + $j.scene_end_frame)
            Write-Host ("Scene percent: " + $j.scene_percent + "%")
            if ($j.summary) {
                Write-Host ""
                Write-Host ("Accepted:      " + $j.summary.accepted_source_instance_count)
                Write-Host ("Unresolved:    " + $j.summary.unresolved_source_instance_count)
                Write-Host ("Probe scenes:  " + $j.summary.scene_probe_ready_count)
                Write-Host ("Preferred:     " + $j.summary.preferred_probe_scene_id)
            }
            if ($j.failures) {
                Write-Host ""
                Write-Host "Failures:"
                $j.failures | ForEach-Object { Write-Host ("- " + $_) }
            }
            if ($j.running -eq $false) {
                Write-Host ""
                Write-Host "Run finished."
                break
            }
        } catch {
            Write-Host "Status file exists but is being updated. Retrying..."
        }
    } else {
        Write-Host "Waiting for the detector to create its status file..."
    }
    Start-Sleep -Seconds 2
}

Write-Host ""
Read-Host "Press Enter to close"
