. (Join-Path $PSScriptRoot 'common.ps1')
Get-ScheduledTask -TaskName $ApiTaskName, $WebTaskName -ErrorAction SilentlyContinue | Select-Object TaskName, State | Format-Table -AutoSize
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $Settings.ApiPort, $Settings.WebPort } | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize
try {
    Invoke-RestMethod -Uri "$PublicUrl/api/health" -TimeoutSec 10 | ConvertTo-Json
    Invoke-RestMethod -Uri "$PublicUrl/api/auth/me" -Headers @{ Origin = $PublicUrl } -TimeoutSec 10 | ConvertTo-Json
} catch { Write-Warning $_.Exception.Message }
