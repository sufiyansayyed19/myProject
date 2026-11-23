# Run Alembic migrations independently for all 4 business services
# Run from project root: .\scripts\migrate_all.ps1

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Alembic = Join-Path $Root ".venv\Scripts\alembic.exe"

$Services = @(
    "services\user-auth-service",
    "services\vehicle-service",
    "services\parking-service",
    "services\payment-service"
)

foreach ($Svc in $Services) {
    Write-Host "`n=== Migrating $Svc ===" -ForegroundColor Cyan
    Push-Location (Join-Path $Root $Svc)
    try {
        & $Alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Migration failed for $Svc" }
    } finally {
        Pop-Location
    }
}

Write-Host "`nAll 4 service databases migrated successfully!" -ForegroundColor Green
