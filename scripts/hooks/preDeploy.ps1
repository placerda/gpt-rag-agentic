# predeploy.ps1 — validate env, optionally load App Config, then build & push

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Colors
# Write-Host will use -ForegroundColor directly

Write-Host ""
Write-Host "🔍 Fetching all 'azd' environment values…"
# This must succeed or we cannot continue
$envValues = azd env get-values

# Parse required values (allow non-fatal failures)
$null = $ErrorActionPreference
$azureContainerRegistryName     = ($envValues | Select-String '^AZURE_CONTAINER_REGISTRY_NAME=' -Quiet:$false).Line -replace '^AZURE_CONTAINER_REGISTRY_NAME=', '' -replace '"',''
$azureContainerRegistryEndpoint = ($envValues | Select-String '^AZURE_CONTAINER_REGISTRY_ENDPOINT=' -Quiet:$false).Line -replace '^AZURE_CONTAINER_REGISTRY_ENDPOINT=', '' -replace '"',''
$azureResourceGroup             = ($envValues | Select-String '^AZURE_RESOURCE_GROUP=' -Quiet:$false).Line -replace '^AZURE_RESOURCE_GROUP=', '' -replace '"',''
$azureAppConfigEndpoint         = ($envValues | Select-String '^AZURE_APP_CONFIG_ENDPOINT=' -Quiet:$false).Line -replace '^AZURE_APP_CONFIG_ENDPOINT=', '' -replace '"',''
$ErrorActionPreference = 'Stop'

# Check for any missing
$missing = @()
if (-not $azureContainerRegistryName)     { $missing += 'AZURE_CONTAINER_REGISTRY_NAME' }
if (-not $azureContainerRegistryEndpoint) { $missing += 'AZURE_CONTAINER_REGISTRY_ENDPOINT' }
if (-not $azureResourceGroup)             { $missing += 'AZURE_RESOURCE_GROUP' }
if (-not $azureAppConfigEndpoint)         { $missing += 'AZURE_APP_CONFIG_ENDPOINT' }

if ($missing.Count -gt 0) {
    Write-Host "`n⚠️  Missing required environment variables:" -ForegroundColor Yellow
    foreach ($var in $missing) {
        Write-Host "    • $var"
    }
    Write-Host ""
    Write-Host "Please set them before running this script, e.g.:"
    Write-Host "  azd env set <NAME> <VALUE>"
    exit 1
}

Write-Host "`n✅ All required azd env values are set.`n" -ForegroundColor Green

Write-Host "🔐 Logging into ACR ($azureContainerRegistryName)…" -ForegroundColor Green
az acr login --name $azureContainerRegistryName

Write-Host "🛢️  Defining TAG…" -ForegroundColor Blue
$tag = $env:TAG
if (-not $tag) {
    $tag = git rev-parse --short HEAD
}
azd env set TAG $tag
Write-Host "✅ TAG set to: $tag" -ForegroundColor Green

Write-Host "`n🛠️  Building Docker image…" -ForegroundColor Green
docker build `
    -t "$azureContainerRegistryEndpoint/azure-gpt-rag/orchestrator-build:$tag" `
    .

Write-Host "`n📤 Pushing image…" -ForegroundColor Green
docker push "$azureContainerRegistryEndpoint/azure-gpt-rag/orchestrator-build:$tag"

Write-Host "`n🧩 Ensuring runtime settings are complete…" -ForegroundColor Green
Write-Host "📦 Creating temporary virtual environment…" -ForegroundColor Blue
$venvPath = 'scripts/appconfig/.venv_temp'
python -m venv $venvPath

# Activate the venv (PowerShell)
Write-Host "→ Activating venv…" -ForegroundColor Blue
& "$venvPath/Scripts/Activate.ps1"

Write-Host "⬇️  Installing requirements…" -ForegroundColor Blue
pip install --upgrade pip
pip install -r scripts/appconfig/requirements.txt

Write-Host "🚀 Running app_defaults.py…" -ForegroundColor Blue
python -m scripts.appconfig.app_defaults

Write-Host "✅ Finished app settings validation." -ForegroundColor Green

# Clean up venv if App Config was used
if ($azureAppConfigEndpoint) {
    Write-Host "`n🧹 Cleaning up…" -ForegroundColor Blue
    # deactivate function is defined by Activate.ps1
    deactivate
    Remove-Item -Recurse -Force $venvPath
}
