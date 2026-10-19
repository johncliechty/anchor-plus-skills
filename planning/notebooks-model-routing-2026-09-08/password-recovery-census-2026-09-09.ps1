$ErrorActionPreference='Stop'
$deadline=[DateTimeOffset]::UtcNow.AddHours(2)
$stopPath=Join-Path $PSScriptRoot 'password-recovery-census-stop-2026-09-09'
$samplePath=Join-Path $PSScriptRoot 'password-recovery-census-2026-09-09.json'
while ([DateTimeOffset]::UtcNow -lt $deadline -and -not (Test-Path -LiteralPath $stopPath)) {
    $counts=@{}
    foreach ($processItem in Get-Process -ErrorAction SilentlyContinue) {
        if ($processItem.ProcessName -in @('python','claude','node','grok','codex','agy')) {
            $counts[$processItem.ProcessName]=1+[int]$counts[$processItem.ProcessName]
        }
    }
    $sample=@{at=[DateTimeOffset]::UtcNow.ToString('o');processes=$counts}
    [IO.File]::WriteAllText($samplePath,($sample | ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    Start-Sleep -Seconds 30
}
