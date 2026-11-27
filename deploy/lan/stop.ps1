param([Parameter(Mandatory = $true)][ValidateSet('Api', 'Web')][string]$Component)
. (Join-Path $PSScriptRoot 'common.ps1')

if ($Component -eq 'Api') {
    & $PythonExe (Join-Path $PSScriptRoot 'check-idle.py')
    if ($LASTEXITCODE -ne 0) { throw 'Wait for queued/running business jobs before stopping the API.' }
}

$taskName = if ($Component -eq 'Api') { $ApiTaskName } else { $WebTaskName }
$port = if ($Component -eq 'Api') { $Settings.ApiPort } else { $Settings.WebPort }
$expectedProcess = if ($Component -eq 'Api') { 'python' } else { 'caddy' }
$pidPath = Join-Path $RuntimeRoot ('pids\{0}.pid' -f $Component.ToLowerInvariant())
$targets = @()
if (Test-Path -LiteralPath $pidPath) {
    $savedId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    $savedProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$savedId" -ErrorAction SilentlyContinue
    if ($savedProcess) {
        # Do not kill a different process if a stale PID was reused.
        $recordedAt = (Get-Item -LiteralPath $pidPath).LastWriteTime
        if ($savedProcess.Name -ne "$expectedProcess.exe" -or -not $savedProcess.CreationDate -or [Math]::Abs(($savedProcess.CreationDate - $recordedAt).TotalSeconds) -gt 15) {
            throw 'Saved process identity no longer matches; inspect the listener before stopping it.'
        }
        $targets = @($savedId)
        $processSnapshot = @(Get-CimInstance Win32_Process)
        for ($index = 0; $index -lt $targets.Count; $index++) {
            $parentId = $targets[$index]
            $targets += @($processSnapshot | Where-Object { $_.ParentProcessId -eq $parentId } | Select-Object -ExpandProperty ProcessId)
        }
    }
}
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
foreach ($listener in $listeners) {
    if ($listener.OwningProcess -notin $targets) { throw 'Listener is not owned by this deployment; refusing to stop it.' }
}

# Ending a Task Scheduler wrapper alone can leave its child server alive.
Stop-ScheduledTask -TaskName $taskName
foreach ($targetId in @($targets | Sort-Object -Descending)) {
    Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 1
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw 'The deployment did not release its port.' }
Write-Output "$Component stopped; port $port released."
