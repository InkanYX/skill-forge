param([Parameter(Mandatory = $true)][ValidateSet('Api', 'Web')][string]$Component)
. (Join-Path $PSScriptRoot 'common.ps1')

$logName = $Component.ToLowerInvariant()
# Keep the previous process logs before a restart; Caddy rotates access logs itself.
foreach ($stream in @('out', 'err')) {
    $logPath = Join-Path $RuntimeRoot "logs\$logName.$stream.log"
    if (Test-Path -LiteralPath $logPath) {
        Move-Item -LiteralPath $logPath -Destination "$logPath.previous" -Force
    }
}

if ($Component -eq 'Api') {
    Set-Location -LiteralPath $BackendRoot
    # Docker Desktop starts after login. Wait for PostgreSQL instead of racing it.
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        $probe = Start-Process -FilePath $PythonExe -ArgumentList '-m app.database_setup check' -WorkingDirectory $BackendRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $RuntimeRoot 'logs\database.out.log') -RedirectStandardError (Join-Path $RuntimeRoot 'logs\database.err.log')
        if ($probe.ExitCode -eq 0) {
            $migrationProbe = Start-Process -FilePath $PythonExe -ArgumentList '-m alembic current --check-heads' -WorkingDirectory $BackendRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $RuntimeRoot 'logs\migration.out.log') -RedirectStandardError (Join-Path $RuntimeRoot 'logs\migration.err.log')
            if ($migrationProbe.ExitCode -eq 0) { $ready = $true; break }
        }
        Start-Sleep -Seconds 15
    }
    if (-not $ready) { throw 'Database or migrations are not ready; see .lan-runtime/logs/database.*.log and migration.*.log. The task will retry.' }
    $executable = $PythonExe
    $arguments = '-m uvicorn app.main:app --host 127.0.0.1 --port {0} --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1' -f $Settings.ApiPort
    $workingDirectory = $BackendRoot
} else {
    $executable = $CaddyExe
    $arguments = 'run --config "{0}" --adapter caddyfile' -f $CaddyConfig
    $workingDirectory = $ProjectRoot
}

$child = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $workingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $RuntimeRoot "logs\$logName.out.log") -RedirectStandardError (Join-Path $RuntimeRoot "logs\$logName.err.log")
$child.Id | Set-Content -LiteralPath (Join-Path $RuntimeRoot "pids\$logName.pid") -Encoding Ascii
$child.WaitForExit()
if ($child.ExitCode -eq 0) { throw "$Component stopped; the scheduled task will restart it." }
exit $child.ExitCode
