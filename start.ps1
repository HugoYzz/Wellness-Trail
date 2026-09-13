# 康迹本地启动脚本（开发期）
# 用法：
#   .\start.ps1            # 同时启动后端(8001)与前端(5173)
#   .\start.ps1 Backend    # 只启动后端
#   .\start.ps1 Frontend   # 只启动前端
#   .\start.ps1 -Lan       # 显式开放局域网（必须已创建访问 PIN）
param(
    [ValidateSet("All", "Backend", "Frontend")]
    [string]$Mode = "All",
    [switch]$Lan
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }

function Test-AccessPinConfigured {
    Push-Location "$root\server"
    try {
        $state = & ".\.venv\Scripts\python.exe" -c `
            "from app.database import engine, SessionLocal; from app.models import Base; from app.services.access_control import pin_is_configured; Base.metadata.create_all(bind=engine); db=SessionLocal(); print('ready' if pin_is_configured(db) else 'missing'); db.close()"
        return ($state | Select-Object -Last 1).Trim() -eq "ready"
    }
    catch {
        return $false
    }
    finally {
        Pop-Location
    }
}

if ($Lan -and -not (Test-AccessPinConfigured)) {
    Write-Error "局域网模式已阻止：请先运行 .\start.ps1，在本机页面创建访问 PIN，再使用 -Lan。"
    exit 1
}

function Start-Backend {
    Start-Process powershell -ArgumentList "-NoProfile", "-Command", `
        "Set-Location '$root\server'; .\.venv\Scripts\python.exe -m alembic upgrade head; if (`$LASTEXITCODE -ne 0) { exit `$LASTEXITCODE }; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host $bindHost --port 8001 --reload" `
        -WindowStyle Hidden
    Write-Host "后端已启动: http://127.0.0.1:8001/api/health（监听 $bindHost）" -ForegroundColor Green
}

function Start-Frontend {
    Start-Process powershell -ArgumentList "-NoProfile", "-Command", `
        "Set-Location '$root\web'; npm run dev -- --host $bindHost" `
        -WindowStyle Hidden
    Write-Host "前端已启动: http://localhost:5173" -ForegroundColor Green
}

if ($Mode -in @("All", "Backend")) { Start-Backend }
if ($Mode -in @("All", "Frontend")) { Start-Frontend }

# 只有显式 -Lan 才打印局域网地址；API 仍由 PIN 会话统一保护。
if ($Lan) {
    $lanAddress = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1).IPAddress
    Write-Host ""
    Write-Host "局域网模式已开启；请只在可信 WiFi 使用。" -ForegroundColor Yellow
    if ($lanAddress) {
        Write-Host "局域网访问: http://$lanAddress`:5173" -ForegroundColor Cyan
    }
} else {
    Write-Host "默认仅本机可访问；需要局域网时使用 .\start.ps1 -Lan。" -ForegroundColor DarkGray
}
