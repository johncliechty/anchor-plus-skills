$dir = 'C:\dev\anchor-build-rearch'
$stop = Join-Path $dir '_census2.stop'
$out = Join-Path $dir '_census.log'
while (-not (Test-Path $stop)) {
    $ts = Get-Date -Format 'HH:mm'
    $c = @(Get-Process claude -ErrorAction SilentlyContinue).Count
    $n = @(Get-Process node -ErrorAction SilentlyContinue).Count
    $p = @(Get-Process python, pythonw -ErrorAction SilentlyContinue).Count
    $a = @(Get-Process agy -ErrorAction SilentlyContinue).Count
    Add-Content -Path $out -Value "$ts claude=$c node=$n python=$p agy=$a" -Encoding ascii
    Start-Sleep -Seconds 60
}
