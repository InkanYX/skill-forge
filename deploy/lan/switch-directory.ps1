$ErrorActionPreference = 'Stop'
$oldRoot = 'D:\project\skill-forge'
$newRoot = 'D:\project\skill-forge-main'
$newRuntime = Join-Path $newRoot '.lan-runtime'
$oldDeploy = Join-Path $oldRoot 'deploy\lan'
$newDeploy = Join-Path $newRoot 'deploy\lan'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator required.' }
Start-Transcript -Path (Join-Path $newRuntime 'logs\switch-directory.log') -Append | Out-Null
$stopped = $false
$complete = $false
try {
    # Protect deployment credentials, copied images, keys and backups.
    $runtimeAcl = Get-Acl -LiteralPath $newRuntime
    $runtimeAcl.SetAccessRuleProtection($true,$false)
    foreach ($account in @($identity.Name,'NT AUTHORITY\SYSTEM','BUILTIN\Administrators')) {
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($account,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
        $runtimeAcl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $newRuntime -AclObject $runtimeAcl
    foreach ($taskName in @('SkillForge-API','SkillForge-Web')) {
        Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $newRuntime "$taskName.before.xml") -Encoding Unicode
    }
    # Block new submissions first, then stop idle API workers.
    & (Join-Path $oldDeploy 'stop.ps1') -Component Web
    $stopped = $true
    & (Join-Path $oldDeploy 'stop.ps1') -Component Api
    & (Join-Path $newRoot 'backend\.venv\Scripts\python.exe') (Join-Path $newDeploy 'upgrade-copy.py')
    if ($LASTEXITCODE -ne 0) { throw 'Database copy or compatibility migration failed; see upgrade report.' }
    # Run installation in a separate PowerShell to keep its variables isolated.
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File (Join-Path $newDeploy 'install.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'New deployment installation failed.' }
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        try {
            $health=Invoke-RestMethod -Uri 'http://192.168.19.136:8080/api/health' -TimeoutSec 3
            if ($health.status -eq 'ok') { $complete=$true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $complete) { throw 'New deployment health check failed.' }
    @{success=$true;root=$newRoot;url='http://192.168.19.136:8080';timestamp=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $newRuntime 'switch-result.json') -Encoding UTF8
    Write-Output 'New directory deployment is healthy.'
} catch {
    @{success=$false;error=$_.Exception.Message;timestamp=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $newRuntime 'switch-result.json') -Encoding UTF8
    if ($stopped -and -not $complete) {
        # Restore old task definitions; the original database and files were never upgraded.
        foreach ($taskName in @('SkillForge-API','SkillForge-Web')) {
            Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        }
        foreach ($component in @('Api','Web')) {
            $pidFile=Join-Path $newRuntime ('pids\{0}.pid' -f $component.ToLowerInvariant())
            if (Test-Path -LiteralPath $pidFile) {
                & (Join-Path $newDeploy 'stop.ps1') -Component $component
            }
        }
        foreach ($taskName in @('SkillForge-API','SkillForge-Web')) {
            Register-ScheduledTask -TaskName $taskName -Xml (Get-Content -LiteralPath (Join-Path $newRuntime "$taskName.before.xml") -Raw) -Force | Out-Null
        }
        $existingRule=Get-NetFirewallRule -Name 'SkillForge-LAN-8080' -ErrorAction SilentlyContinue
        if ($existingRule) { $existingRule | Get-NetFirewallApplicationFilter | Set-NetFirewallApplicationFilter -Program (Join-Path $oldRoot '.lan-runtime\bin\caddy.exe') | Out-Null }
        Start-ScheduledTask -TaskName SkillForge-API
        Start-ScheduledTask -TaskName SkillForge-Web
    }
    Write-Error $_
    exit 1
} finally { Stop-Transcript | Out-Null }
