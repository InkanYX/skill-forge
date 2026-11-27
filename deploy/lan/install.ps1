param([switch]$ReplaceExistingApi)
. (Join-Path $PSScriptRoot 'common.ps1')

$resultPath = Join-Path $RuntimeRoot 'install-result.json'
Start-Transcript -Path (Join-Path $RuntimeRoot 'logs\install.log') -Append | Out-Null
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this installer from an administrator PowerShell.'
    }
    foreach ($required in @($PythonExe, $CaddyExe, (Join-Path $ProjectRoot 'frontend\dist\index.html'))) {
        if (-not (Test-Path -LiteralPath $required)) { throw "Missing deployment prerequisite: $required" }
    }
    $network = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $Settings.LanAddress -ErrorAction Stop
    & $CaddyExe validate --config $CaddyConfig --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'Caddy validation failed.' }
    Push-Location -LiteralPath $BackendRoot
    try {
        & $PythonExe -m app.database_setup check
        if ($LASTEXITCODE -ne 0) { throw 'Database check failed.' }
        & $PythonExe -m alembic current --check-heads
        if ($LASTEXITCODE -ne 0) { throw 'Apply pending database migrations before installing the deployment.' }
        # Never replace an API while images or Agent runs are queued or running.
        & $PythonExe (Join-Path $PSScriptRoot 'check-idle.py')
        if ($LASTEXITCODE -ne 0) { throw 'Wait for queued/running business tasks before replacing the API.' }
    } finally { Pop-Location }

    $listener = @(Get-NetTCPConnection -State Listen -LocalPort $Settings.ApiPort -ErrorAction SilentlyContinue)
    $existingApiTask = Get-ScheduledTask -TaskName $ApiTaskName -ErrorAction SilentlyContinue
    $existingWebTask = Get-ScheduledTask -TaskName $WebTaskName -ErrorAction SilentlyContinue
    if ($existingApiTask -and $existingApiTask.State -eq 'Running') { throw 'API deployment task is already running. Stop it explicitly before reinstalling.' }
    if ($existingWebTask -and $existingWebTask.State -eq 'Running') { throw 'Web deployment task is already running. Stop it explicitly before reinstalling.' }
    if (Get-NetTCPConnection -State Listen -LocalPort $Settings.WebPort -ErrorAction SilentlyContinue) { throw 'The public web port is already in use.' }

    if ($listener) {
        if (-not $ReplaceExistingApi) { throw 'API port is occupied. Use -ReplaceExistingApi to replace the verified development server.' }
        $processIds = @($listener | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($processId in $processIds) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
            $parent = Get-CimInstance Win32_Process -Filter ('ProcessId={0}' -f $process.ParentProcessId)
            $server = if ($parent -and $parent.Name -eq 'python.exe' -and $parent.CommandLine -match 'uvicorn.*app\.main:app') { $parent } else { $process }
            if ($server.Name -ne 'python.exe' -or $server.CommandLine -notmatch 'uvicorn.*app\.main:app') { throw 'Refusing to stop an unidentified process on the API port.' }
            Write-Output ('Stopping verified development API PID {0} (listener PID {1}).' -f $server.ProcessId, $processId)
            # Stop the reload supervisor first so it cannot recreate its child.
            Stop-Process -Id $server.ProcessId -Force -ErrorAction Stop
            if ($server.ProcessId -ne $processId) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }
        }
        Start-Sleep -Seconds 2
        if (Get-NetTCPConnection -State Listen -LocalPort $Settings.ApiPort -ErrorAction SilentlyContinue) { throw 'The old API did not release its port.' }
    }

    # Run with the existing admin account's limited token, not as SYSTEM.
    # S4U stores no password; HTTP provider calls do not require Windows credentials.
    $taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType S4U -RunLevel Limited
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
    $taskSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    foreach ($component in @('Api', 'Web')) {
        $taskName = if ($component -eq 'Api') { $ApiTaskName } else { $WebTaskName }
        $arguments = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "{0}" -Component {1}' -f (Join-Path $PSScriptRoot 'run.ps1'), $component
        $action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments -WorkingDirectory $ProjectRoot
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startupTrigger, $logonTrigger) -Settings $taskSettings -Principal $taskPrincipal -Description "Skill Forge LAN $component; deployment files in $PSScriptRoot" -Force | Out-Null
    }
    $firewallName = 'SkillForge-LAN-8080'
    $oldRule = Get-NetFirewallRule -Name $firewallName -ErrorAction SilentlyContinue
    if ($oldRule) {
        if ($oldRule.Group -ne 'SkillForge LAN') { throw 'Firewall rule name is already used by another application.' }
        $oldRule | Remove-NetFirewallRule
    }
    New-NetFirewallRule -Name $firewallName -DisplayName 'Skill Forge LAN 8080' -Group 'SkillForge LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Settings.WebPort -LocalAddress $Settings.LanAddress -RemoteAddress LocalSubnet -InterfaceAlias $network.InterfaceAlias -Profile Any -Program $CaddyExe | Out-Null
    Start-ScheduledTask -TaskName $ApiTaskName
    Start-ScheduledTask -TaskName $WebTaskName
    @{ success = $true; url = $PublicUrl; user = $identity.Name; timestamp = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Output "Deployment tasks started. Open $PublicUrl"
} catch {
    @{ success = $false; error = $_.Exception.Message; timestamp = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Error $_
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
