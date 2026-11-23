# Start all 4 business services + API Gateway in separate PowerShell windows
# Run from project root: .\scripts\start_all.ps1

$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Uvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"

if (-not (Test-Path $Uvicorn)) {
    Write-Error "Virtual environment uvicorn not found at $Uvicorn. Create .venv and install requirements.txt first."
    exit 1
}

$Apps = @(
    @{ Name = "User/Auth Service (8001)"; Dir = Join-Path $Root "services\user-auth-service"; Port = 8001 },
    @{ Name = "Vehicle Service (8002)";   Dir = Join-Path $Root "services\vehicle-service";   Port = 8002 },
    @{ Name = "Parking Service (8003)";   Dir = Join-Path $Root "services\parking-service";   Port = 8003 },
    @{ Name = "Payment Service (8004)";   Dir = Join-Path $Root "services\payment-service";   Port = 8004 },
    @{ Name = "API Gateway (8000)";       Dir = Join-Path $Root "gateway";                    Port = 8000 }
)

foreach ($App in $Apps) {
    $Cmd = "`$Host.UI.RawUI.WindowTitle = '$($App.Name)'; Set-Location '$($App.Dir)'; & '$Uvicorn' app.main:app --port $($App.Port) --reload"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $Cmd
}

Write-Host "Started all 5 apps!" -ForegroundColor Green
Write-Host "  API Gateway:       http://127.0.0.1:8000/health"
Write-Host "  User/Auth Swagger: http://127.0.0.1:8001/docs"
Write-Host "  Vehicle Swagger:   http://127.0.0.1:8002/docs"
Write-Host "  Parking Swagger:   http://127.0.0.1:8003/docs"
Write-Host "  Payment Swagger:   http://127.0.0.1:8004/docs"
