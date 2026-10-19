param([string]$StatePath)
$ErrorActionPreference = 'Stop'
$censusPath = Join-Path (Split-Path -Parent $StatePath) 'implementation-census.json'
$censusDeadline = [DateTimeOffset]::UtcNow.AddHours(12)
while ([DateTimeOffset]::UtcNow -lt $censusDeadline) {
    $counts = @{}
    foreach ($procItem in (Get-Process -ErrorAction SilentlyContinue)) {
        if ($procItem.ProcessName -in @('python','claude','node','grok','codex','agy')) {
            $counts[$procItem.ProcessName] = 1 + [int]$counts[$procItem.ProcessName]
        }
    }
    $sample = @{at=[DateTimeOffset]::UtcNow.ToString('o'); processes=$counts}
    try {
        $currentState = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json
        $sample['state'] = $currentState
        if ($currentState.status -in @('complete','blocked','stopped')) { break }
    } catch {
        $sample['state_read_error'] = $_.Exception.GetType().Name
    }
    $sampleText = $sample | ConvertTo-Json -Depth 6 -Compress
    [System.IO.File]::WriteAllText($censusPath, $sampleText, [System.Text.UTF8Encoding]::new($false))
    Write-Output $sampleText
    Start-Sleep -Seconds 60
}
Write-Output 'Implementation census stopped.'
