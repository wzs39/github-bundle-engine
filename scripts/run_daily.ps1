# 一键日更: 热点发现 -> 刷新专题 -> 构建 -> 校验 -> 排程
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts\run_daily.ps1 -Out OUTPUT_DIR
#   可选: -NoApply (只出报告不写回 topics.json)  -SkipBuild  -Fixture <json> (离线试跑)
# 计划任务示例 (每天 08:30, 在仓库根目录执行):
#   schtasks /Create /TN "GitHubBundleDaily" /SC DAILY /ST 08:30 ^
#     /TR "powershell -ExecutionPolicy Bypass -File <仓库根>\scripts\run_daily.ps1 -Out <仓库根>\OUTPUT_DIR"
param(
    [string]$Out = "OUTPUT_DIR",
    [switch]$NoApply,
    [switch]$SkipBuild,
    [string]$Fixture = ""
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not $env:GITHUB_TOKEN) {
    $envFile = Join-Path $repoRoot ".env"
    if (Test-Path $envFile) {
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^\s*GITHUB_TOKEN\s*=\s*(\S+)\s*$") { $env:GITHUB_TOKEN = $Matches[1] }
        }
    }
}

$stamp = Get-Date -Format "yyyyMMdd"
$logPath = Join-Path $repoRoot ("OUTPUT_DIR\logs\daily_" + $stamp + ".log")
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null

$cliArgs = @("-m", "src.cli", "daily", "--out", $Out)
if ($NoApply)   { $cliArgs += "--no-apply" }
if ($SkipBuild) { $cliArgs += "--skip-build" }
if ($Fixture)   { $cliArgs += "--fixture", $Fixture }

"==== daily run start $(Get-Date -Format o) ====" | Tee-Object -FilePath $logPath -Append
python @cliArgs 2>&1 | Tee-Object -FilePath $logPath -Append
$code = $LASTEXITCODE
"==== daily run end code=$code $(Get-Date -Format o) ====" | Tee-Object -FilePath $logPath -Append
exit $code
