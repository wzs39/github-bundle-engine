# 运营 SOP · Day 1–7 搭建期 + 稳定期每日 90 分钟

配套引擎：`github-bundle-engine/`。所有命令在引擎根目录执行，Windows 下 `python` 可换成 `py -3`。占位值统一用 `[GITHUB_TOKEN]`、`[PAN_SHARE_URL]`、`[PAN_EXTRACT_CODE]`、`[PAN_PROMOTE_UID]`。

---

## Day 1 — 环境、账号、权限

| 时段 | 动作 | 命令 / 落点 |
| --- | --- | --- |
| 15 min | 闲鱼独立号实名 + 芝麻信用授权；与日常实物买卖主力号严格分离 | 人工 |
| 15 min | 前 2 天每天浏览效率工具与源码类商品 15 分钟，养基础活跃权重 | 人工 |
| 20 min | 注册网盘官方合作一级服务商（任推邦 / 星子助推 / 洽立方），申请夸克（主力高单价）+ 百度网盘推广权限，绑定专用存储 UID 并完成渠道报备 | 服务商后台 → `[PAN_PROMOTE_UID]` |
| 10 min | 配置闲鱼网页版后台自动回复 / 低成本自动发货插件，付款后 3 秒内发链接 | `[XIANYU_AUTO_REPLY_PLUGIN]` |
| 15 min | Python 3.9+ 自检 + 离线全链路试跑 | `powershell -ExecutionPolicy Bypass -File scripts/run_day1.ps1` |
| 15 min | 核对 `OUTPUT_DIR/` 产出的四级目录、上架物料、日报样例 | `python -m src.cli verify --out OUTPUT_DIR` |

`run_day1.ps1` 会依次做：Python 版本 → 配置齐全检查 → 环境变量缺值提示 → `selftest` → `verify` → `economics.py`。缺 key / UID / 插件只给待补提示，不中断离线试跑。

可选但建议：`set GITHUB_TOKEN=[GITHUB_TOKEN]`。未认证时 GitHub Search API 只有 60 次/小时，脚本内置 `X-RateLimit-Reset` 退避、2 秒最小间隔、4 次重试与镜像前缀回退。

## Day 2 — 养号续 + 抓取脚本调参

- 继续 15 分钟浏览养号。
- 按实际网速调 `config/settings.json` 的 `timeout_seconds` / `min_interval_seconds` / `download_mirrors`。
- 需要换选品就改 `config/topics.json`：标签、Star 门槛、`pushed_after_days`、`repo_limit`、定价、长尾词。
- 跑一次单专题真实抓取，确认合规闸排除记录符合预期：

```bash
python -m src.cli build --topic py-office --out OUTPUT_DIR
python -m src.cli verify --out OUTPUT_DIR
```

看日志里每一条 `排除 owner/repo -> 原因`，确认黑名单、协议白名单、LICENSE 归档校验三层都在工作。

## Day 3–5 — 每天 2 个专题包

```bash
python -m src.cli build --topic local-ai --out OUTPUT_DIR
python -m src.cli build --topic grad-project --out OUTPUT_DIR
python -m src.cli verify --out OUTPUT_DIR
```

每个包生成后：

1. 打开 `00_项目清单与中文简介说明.md` 复核「这套合集解决什么」三段导语——引擎已从 `config/topics.json` 自动注入，各专题三段不同，同时进 `_manifest.json` 和闲鱼详情页；只需按实际收录项目微调措辞，不用再从零写。
2. 把**整个解压后的多级目录**上传网盘，保持 `00 / 01 / 02 / 03` 结构，不要压成单个死压缩包。
3. 在服务商后台用**已报备的推广渠道**生成分享链接，拿到 `[PAN_SHARE_URL]` 与 `[PAN_EXTRACT_CODE]`。
4. 用 `bind-pan` 正式回填（**拒占位符**，必须真实链）：

```bash
python -m src.cli bind-pan --topic local-ai ^
  --share-url [PAN_SHARE_URL] --extract-code [PAN_EXTRACT_CODE] ^
  --promote-uid [PAN_PROMOTE_UID] --out OUTPUT_DIR

python -m src.cli verify --out OUTPUT_DIR
```

`bind-pan` 会写 `_manifest.json` 的 `pan` 段（`share_url` / `extract_code` / `bound_at` / `channel_reported` / `settlement: T+1`）并原子重写 `auto_reply.txt`，写回前重扫红线。`build` 时直接传这两个真实参数也会自动走这一步；传占位链只保留文案占位、不写 manifest。`verify` 末尾会打印「推广链绑定: N/M」。

体积目标 500MB–2GB：太小没有干货感，太大转存慢。`_manifest.json` 的 `size_ok` 字段会标出是否落在区间内；纯源码专题偏小时，靠多收录仓库或补官方 Release 安装包撑起来。

## Day 6–7 — 首批 4–6 个链接冷启动

先生成排程表，照表操作即可，不用再手排时间：

```bash
python -m src.cli schedule --start 2026-09-17T09:00:00 ^
  --days 7 --per-day 2 --interval 60 --existing-links 4 --out OUTPUT_DIR
```

产出 `reports/schedule_<date>.json` 与 `.md`：14 个槽、每天 09:00 / 10:00、间隔 60 分钟、库存 50–99、链接数从 4 演进到 18。长尾词按「专题自身出现轮次」轮转（例如 `local-ai` 四轮分别取 `本地大模型/ollama/comfyui`、`ollama/comfyui/AI 工具合集`、`comfyui/AI 工具合集/本地大模型`、`AI 工具合集/本地大模型/ollama`），不会像原来那样 4 个链接撞回同一组词。有效链接到 25 后自动把新槽切成「擦亮 / 衍生」而不是继续硬新增。表里 `[待补] 该专题尚未 bind-pan` 的槽先补齐推广链再上架。

- 标题取排程表的 `title`（或 `listings/<id>/listing_plan.json` 的 `title`）；主图 = 目录截图 + 痛点大字（用 `selling_point`）。
- 详情页粘 `xianyu_detail.md`；自动发货粘 `auto_reply.txt`（`bind-pan` 后已含真实链）。
- 第 7 天结束前跑一次复盘：

```bash
python -m src.cli report --out OUTPUT_DIR --links 6 --exposures 240 --wants 12 --orders 1 ^
  --front-revenue 0.99 --pan-new 1 --pan-saves 3 --pan-commission 8.5
```

里程碑 ① 判定：至少 1 笔真实成交 + 服务商后台首笔拉新佣金到账。

---

## 稳定运营期 · 每日 90 分钟

### 前 25 分钟 — 脚本抓取与扩品

```bash
python -m src.cli build --topic <今天的新细分专题> --out OUTPUT_DIR
python -m src.cli verify --out OUTPUT_DIR
```

新增 1 个细分专题包并上传网盘，让货架有效链接稳定在 **15–25 个**。每周往老网盘文件夹追加新项目（不换链接），激活老买家二次转存收益。

### 中间 35 分钟 — 闲鱼上架与流量优化

1. 全店商品点「擦亮」。
2. 拉前 48 小时数据：**曝光 < 100 且零「想要」** 的链接直接删除重发，换主图与长尾词（新词从 `listing_plan.json` 的 `long_tail_keywords` + `derivative_links` 取）。
3. 出单好的链接，用不同封面图衍生 1–2 个细分长尾链接。
4. 新链接间隔 ≥ 60 分钟，别一口气全上。

### 最后 30 分钟 — 售后维护与数据复盘

1. 回复环境配置咨询；把高频问题追加进 `01_新手环境配置与国内镜像加速.txt`（引擎里已有 pip / npm / Maven 国内源 + FAQ 骨架），然后重新上传该单文件覆盖网盘旧版。
2. 核对服务商后台 T+1 拉新与转存数据，淘汰拉新转化率 < 5% 的低效链接。
3. 用真实数字出日报：

```bash
python -m src.cli report --out OUTPUT_DIR --date 2026-09-17 ^
  --links 20 --exposures 2100 --wants 96 --orders 7 ^
  --front-revenue 32.5 --pan-new 3 --pan-saves 24 --pan-commission 33.6
```

`daily_<date>.json` 会算前端收益、网盘佣金、合计、转化率，并列出当日 5 条固定动作。

### 收益模型对照

```bash
python scripts/economics.py
```

| 场景 | 链接 | 订单/日 | 前端 | 网盘低–高 | 合计低–高 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 第一阶段·跑通闭环 | 4 | 1 | 0.99 | 7.9–13.5 | 8.89–14.49 |
| 第二阶段·20 链接 | 20 | 5 | 17.50 | 19.4–33.0 | 36.90–50.50 |
| 第二阶段·爆款 | 22 | 10 | 42.00 | 37.0–63.0 | 79.00–105.00 |
| 第三阶段·稳定 | 20 | 8 | 30.40 | 28.8–49.0 | 59.20–79.40 |

策略书目标 40–120 元/日由「第二阶段·爆款」与「第三阶段·稳定」覆盖。关键杠杆：有效链接 15–25、拉新转化 ≥ 5%、老买家每周追加更新触发二次转存。

---

## 红线清单（每次发货前扫一遍）

1. 每个项目原 `LICENSE` 与作者链接完整保留；`_manifest.json` 里 `license_in_archive` 非空才算过闸。
2. 详情页统一声明「本合集源码均整理自 GitHub 公开开源社区，遵循原项目开源协议，所收费用仅为人工分类整理、中文说明编写及网盘整理服务费」。
3. 对话框与自动发货文案不出现微信号、QQ 号、手机号、二维码；`verify` 用 `check_text` 做红线扫描。
4. 不写「必须下载某 App 才能发货」；用温和引导：「资源已整理存入网盘，因开源文件夹较大，建议保存至个人网盘后按需下载，内附中文部署清单」。
5. 抓取脚本过滤渗透测试 / 攻击 / 破解 / 翻墙代理类仓库（`config/compliance.json` 黑名单）。
6. 不用接码平台、模拟器自刷网盘拉新佣金；渠道链接必须是已报备 UID 生成的真实推广链。

## 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `403 rate limit exceeded` | 未设 `GITHUB_TOKEN` | 设 token；脚本已按 `X-RateLimit-Reset` 自动等待 |
| 源码下载超时 | codeload 直连不稳 | 在 `download_mirrors` 填 `[MIRROR_PREFIX_1]` 等实际前缀，脚本逐个回退 |
| `LICENSE 缺失, 拒绝收录` | 归档里确实没有 / 在子目录 | 属预期行为，该仓库进 `excluded` 记录，换下一个 |
| 包体积 `size_ok=false` | 纯源码专题偏小 | 提高 `repo_limit` 或补官方 Release 安装包；目标 500MB–2GB |
| `verify` 报文案红线 | 手改文案带进了联系方式 | 按报出的行改回，再跑 `verify` |
| `verify` 把 SHA-256 摘要当手机号 | 旧版手机号正则缺词法边界 | 已加 `(?<![A-Za-z0-9])…(?![A-Za-z0-9])`，摘要放行、真实 11 位号码仍拦 |
| `bind-pan` 返回 1 | 传了 `[PAN_SHARE_URL]` 占位符或非 http(s) 链 | 换成已报备 UID 生成的真实推广链与真实提取码 |
| `schedule` 提示未绑定 | 该专题 `_manifest.json` 的 `pan.share_url` 为空 | 先跑 `bind-pan`，排程表里的 `[待补]` 才会消失 |
| 重建后老买家链接失效 | 旧版 `build` 直接 `rmtree` 删掉了 `pan` 段与 FAQ | 现已在重建前抢救 `pan` 段与「## 买家高频咨询补充」段落并回写，manifest 留 `rebuild_preserved` 标记 |
| 网盘后台无佣金 | 用了普通分享链而非报备推广链 | 用 `[PAN_PROMOTE_UID]` 对应渠道重新生成链接并 `bind-pan` |
