# Day 1 环境自检与首包试跑 (Windows PowerShell)
# 用法: powershell -ExecutionPolicy Bypass -File scripts/run_day1.ps1
# 全部占位值按策略书 2.1 由使用者在服务商后台补齐后替换.

$ErrorActionPreference = "Stop"
$EngineRoot = Split-Path -Parent $PSScriptRoot
Set-Location $EngineRoot

function Info($msg) { Write-Host "[day1] $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "[day1][待补] $msg" -ForegroundColor Yellow }

Info "1/6 Python 版本"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "未找到 python / py, 先安装 Python 3.9+" }
& $py.Source --version

Info "2/6 目录与配置"
$must = @(
  "config/topics.json",
  "config/settings.json",
  "config/compliance.json",
  "templates/declaration.txt",
  "src/cli.py"
)
foreach ($f in $must) {
  if (-not (Test-Path (Join-Path $EngineRoot $f))) { throw "缺文件 $f" }
}
Info "配置齐全"

Info "3/6 可选环境变量 (缺值用占位符继续, 不阻塞离线试跑)"
if (-not $env:GITHUB_TOKEN) { Warn "GITHUB_TOKEN 未设置 -> 真实 build 走未认证限速 (60 次/小时)" }
if (-not $env:PAN_PROMOTE_UID) { Warn "PAN_PROMOTE_UID 未设置 -> 去任推邦/星子助推/洽立方申请夸克+百度网盘推广权" }
if (-not $env:XIANYU_AUTO_REPLY_PLUGIN) { Warn "XIANYU_AUTO_REPLY_PLUGIN 未设置 -> 闲鱼网页版后台自动回复待配置" }
Info "网盘分享链接占位: [PAN_SHARE_URL] / [PAN_EXTRACT_CODE]"

Info "4/6 离线全链路自检 (4 个专题 + 场景导语 + 上架物料 + 日报)"
& $py.Source -m src.cli selftest --all-topics --out OUTPUT_DIR
if ($LASTEXITCODE -ne 0) { throw "selftest 失败" }

Info "5/6 产物校验 (四级目录 / LICENSE / 合规声明 / 文案红线 / 推广链绑定数)"
& $py.Source -m src.cli verify --out OUTPUT_DIR
if ($LASTEXITCODE -ne 0) { throw "verify 失败" }

Info "6/6 上架排程 + 收益模型验算"
& $py.Source -m src.cli schedule --days 7 --per-day 2 --interval 60 --existing-links 4 --out OUTPUT_DIR
if ($LASTEXITCODE -ne 0) { throw "schedule 失败" }
& $py.Source scripts/economics.py

Info "Day 1 完成. 产物在 OUTPUT_DIR/, 排程在 OUTPUT_DIR/reports/schedule_*.md"
Warn "Day 1-2 还要做: 闲鱼独立号养号(每天 15 分钟) + 网盘渠道报备"
Warn "Day 3-5 跑: python -m src.cli build --all --out OUTPUT_DIR"
Warn "拿到真实推广链后: python -m src.cli bind-pan --topic <id> --share-url <URL> --extract-code <CODE> --out OUTPUT_DIR"
