param([ValidatePattern('^[A-Za-z0-9_]+$')][string]$Revision = 'head')
. (Join-Path $PSScriptRoot 'common.ps1')

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this updater from an administrator PowerShell.'
}
Start-Transcript -Path (Join-Path $RuntimeRoot 'logs\update.log') -Append | Out-Null
try {
    & $PythonExe (Join-Path $PSScriptRoot 'check-idle.py')
    if ($LASTEXITCODE -ne 0) { throw 'Wait for business tasks to finish before updating.' }
    $backupDirectory = Join-Path $RuntimeRoot 'backups'
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    $backupAcl = Get-Acl -LiteralPath $backupDirectory
    $backupAcl.SetAccessRuleProtection($true, $false)
    foreach ($backupIdentity in @($identity.Name, 'NT AUTHORITY\SYSTEM', 'BUILTIN\Administrators')) {
        $backupRule = New-Object System.Security.AccessControl.FileSystemAccessRule($backupIdentity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $backupAcl.AddAccessRule($backupRule)
    }
    Set-Acl -LiteralPath $backupDirectory -AclObject $backupAcl
    # Inspect credentials only in memory; never print container environment values.
    $container = docker inspect skill-forge-postgres | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the PostgreSQL container.' }
    $userEntry = @($container[0].Config.Env | Where-Object { $_ -like 'POSTGRES_USER=*' })
    $postgresUser = if ($userEntry.Count) { $userEntry[0].Substring(14) } else { 'postgres' }
    $backupName = 'skill-forge-before-update-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.dump'
    $databaseName = & $PythonExe -c 'import sys; from dotenv import dotenv_values; from sqlalchemy.engine import make_url; print(make_url(list(dotenv_values(sys.argv[1]).values())[0]).database)' (Join-Path $RuntimeRoot 'deployment.env')
    if ($LASTEXITCODE -ne 0 -or $databaseName -notmatch '^[A-Za-z0-9_]+$') { throw 'Cannot determine deployment database name.' }
    docker exec skill-forge-postgres pg_dump -U $postgresUser -d $databaseName -Fc -f "/tmp/$backupName"
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL backup failed; no service was stopped.' }
    docker cp "skill-forge-postgres:/tmp/$backupName" (Join-Path $backupDirectory $backupName)
    if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed; no service was stopped.' }
    & (Join-Path $PSScriptRoot 'stop.ps1') -Component Api
    Push-Location -LiteralPath $BackendRoot
    try {
        & $PythonExe -m alembic upgrade $Revision
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed; inspect the migration log before retrying.' }
        & $PythonExe -m alembic current --check-heads
        if ($LASTEXITCODE -ne 0) { throw 'Pending database migrations remain.' }
    } finally {
        Pop-Location
        Start-ScheduledTask -TaskName $ApiTaskName
    }

    # Capture privileged firewall verification for later read-only troubleshooting.
    $rule = Get-NetFirewallRule -Name 'SkillForge-LAN-8080'
    $addresses = $rule | Get-NetFirewallAddressFilter
    $ports = $rule | Get-NetFirewallPortFilter
    $application = $rule | Get-NetFirewallApplicationFilter
    @{
        url = $PublicUrl
        backup = Join-Path $backupDirectory $backupName
        firewall = @{
            enabled = [string]$rule.Enabled
            direction = [string]$rule.Direction
            action = [string]$rule.Action
            profile = [string]$rule.Profile
            localAddress = $addresses.LocalAddress
            remoteAddress = $addresses.RemoteAddress
            localPort = $ports.LocalPort
            program = $application.Program
        }
        timestamp = (Get-Date).ToString('o')
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $RuntimeRoot 'deployment-audit.json') -Encoding UTF8
    Write-Output "Backend update completed. Open $PublicUrl"
} catch {
    Write-Error $_
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
