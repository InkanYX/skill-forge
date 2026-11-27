$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Settings = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'settings.psd1')
$RuntimeRoot = Join-Path $ProjectRoot '.lan-runtime'
$BackendRoot = Join-Path $ProjectRoot 'backend'
$PythonExe = Join-Path $BackendRoot '.venv\Scripts\python.exe'
$CaddyExe = Join-Path $RuntimeRoot 'bin\caddy.exe'
$CaddyConfig = Join-Path $PSScriptRoot 'Caddyfile'
$PublicUrl = 'http://{0}:{1}' -f $Settings.LanAddress, $Settings.WebPort
$ApiTaskName = 'SkillForge-API'
$WebTaskName = 'SkillForge-Web'
$deploymentConfig = Join-Path $RuntimeRoot 'deployment.env'
if (Test-Path -LiteralPath $deploymentConfig) {
    # Keep the developer's backend/.env and test database untouched.
    $env:SKILL_FORGE_DEPLOYMENT_ENV = $deploymentConfig
    $deploymentValues = & $PythonExe -c 'import json,sys; from dotenv import dotenv_values; print(json.dumps(dict(dotenv_values(sys.argv[1]))))' $deploymentConfig
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read deployment environment.' }
    $values = $deploymentValues | ConvertFrom-Json
    $env:DATABASE_URL = $values.DATABASE_URL
    $env:SKILL_FORGE_DATA_DIR = $values.SKILL_FORGE_DATA_DIR
}
$env:SKILL_FORGE_LAN_ADDRESS = $Settings.LanAddress
$env:SKILL_FORGE_WEB_PORT = [string]$Settings.WebPort
$env:SKILL_FORGE_API_PORT = [string]$Settings.ApiPort
$env:SKILL_FORGE_FRONTEND_ROOT = (Join-Path $ProjectRoot 'frontend\dist').Replace('\', '/')
$env:SKILL_FORGE_RUNTIME = $RuntimeRoot.Replace('\', '/')
$env:SKILL_FORGE_ALLOWED_HOSTS = '127.0.0.1,localhost,{0}' -f $Settings.LanAddress
$env:SKILL_FORGE_ALLOWED_ORIGINS = $PublicUrl
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
$env:XDG_CONFIG_HOME = Join-Path $RuntimeRoot 'config'
$env:XDG_DATA_HOME = Join-Path $RuntimeRoot 'data'
New-Item -ItemType Directory -Path (Join-Path $RuntimeRoot 'logs'), (Join-Path $RuntimeRoot 'pids') -Force | Out-Null
