# 康迹本地 AI 运行环境准备脚本。
# 前置条件：已从 https://ollama.com/download 安装并启动 Ollama。
param(
    [switch]$SkipPythonDependencies,
    [switch]$SkipModels
)

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pythonPath = Join-Path $projectRoot "server\.venv\Scripts\python.exe"

if (-not $SkipPythonDependencies) {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "未找到 server\.venv，请先创建 Python 3.12 虚拟环境。"
    }
    & $pythonPath -m pip install "qdrant-client>=1.12" "pymupdf>=1.24"
    if ($LASTEXITCODE -ne 0) { throw "Python RAG 依赖安装失败。" }
}

if (-not $SkipModels) {
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    if (-not $ollamaCommand) {
        throw "未检测到 Ollama。请先安装并启动 Ollama，再重新运行本脚本。"
    }
    & ollama pull qwen3.5:4b
    if ($LASTEXITCODE -ne 0) { throw "下载 qwen3.5:4b 失败。" }
    & ollama pull qwen3-embedding:0.6b
    if ($LASTEXITCODE -ne 0) { throw "下载 qwen3-embedding:0.6b 失败。" }
}

Write-Host "本地 AI 依赖已准备完成。" -ForegroundColor Green
Write-Host "如需启用向量检索，请在 server/.env 设置 RAG_VECTOR_ENABLED=1，然后重启后端并在设置页重建索引。" -ForegroundColor Cyan
