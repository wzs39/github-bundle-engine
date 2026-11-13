# github-bundle-engine

GitHub 热门开源项目自动化打包引擎。按策略书把「GitHub 抓取 → 合规过滤 → 标准化专题目录 → 中文场景导语 → 闲鱼上架物料 → 网盘推广链绑定 → 上架排程 → 每日复盘」做成可复跑的本地流水线。

零第三方依赖，Python 3.9+ 标准库即可运行。产物是**解压后的多级目录**（不压成单个死压缩包），直接上传网盘即可让买家预览并一键转存。

> **要看「需要我准备什么」：直接读 [docs/PREREQUISITES.md](docs/PREREQUISITES.md)**，或跑 `python scripts/check_prereqs.py` 逐项自检（只读、不联网、不回显凭据）。离线 `selftest` 不需要任何外部输入；真实抓取/上架/结算需要 A 类 5 项硬门槛。

## 目录

```
github-bundle-engine/
├── config/
│   ├── topics.json        4 个垂直专题: 标签 / Star 门槛 / 定价 / 长尾词 / 三段中文场景导语
│   ├── settings.json      API 根 / 限流 / 镜像 / 网盘与闲鱼参数
│   └── compliance.json    内容黑名单 / 协议白名单 / 资产上限 / 声明路径
├── src/
│   ├── gh_client.py       GitHub Search + Release + 源码/资产下载, 含限流退避与 SHA-256
│   ├── compliance.py      仓库筛选 / 资产筛选 / LICENSE 校验 / 文案红线扫描
│   ├── downloader.py      tar 安全解包 (路径穿越防护 / 体积上限 / 原子写 JSON)
│   ├── packer.py          标准化 4 级目录 + 中文清单(含场景导语) + _manifest.json
│   ├── listing.py         闲鱼标题 / 详情 / 自动发货 / 上架计划 / 日报 JSON
│   ├── pan.py             推广链接校验 + 回填 _manifest.json + 重生成发货文案
│   ├── scheduler.py       上架排程: 间隔 >= 60min / 长尾词轮转 / 25 链接封顶
│   └── cli.py             build / bind-pan / schedule / verify / report / selftest
├── templates/
│   ├── declaration.txt    详情页统一合规声明 (含中文标点, 由文件读取而非硬编码)
│   └── xianyu_detail.md.tpl
├── scripts/
│   ├── check_prereqs.py   开工前自检: A/B/D 三类逐项打印已就绪/待补
│   ├── economics.py       双引擎收益模型验算
│   └── run_day1.ps1       Day 1 环境自检占位脚本
├── tests/
│   └── test_engine.py     unittest 离线回归
├── .env.example           本地凭据模板 (复制为 .env 后填真实值)
└── docs/
    ├── PREREQUISITES.md   需要你准备什么 / 验收命令 / 给我什么格式
    └── ops-sop.md         Day 1–7 搭建期 + 每日 90 分钟 SOP
```

## 快速开始

先看差距再动手：

```bash
python scripts/check_prereqs.py                 # 逐项打印「已就绪 / 待补」
```

```bash
# 1) 离线跑通全链路 (不联网, 夹具生成 4 个专题包 + 上架物料 + 场景导语 + 日报)
python -m src.cli selftest --all-topics --out OUTPUT_DIR

# 2) 校验产物: 四级目录 / LICENSE / 合规声明 / 文案红线 / 推广链绑定数
python -m src.cli verify --out OUTPUT_DIR

# 3) 回填已报备渠道生成的推广链 (占位符会被拒绝, 必须真实链)
python -m src.cli bind-pan --topic py-office ^
  --share-url [PAN_SHARE_URL] --extract-code [PAN_EXTRACT_CODE] ^
  --promote-uid [PAN_PROMOTE_UID] --out OUTPUT_DIR

# 4) 生成 Day 6-7 / 稳定期上架排程 (间隔 60 分钟, 库存 50-99, 长尾词轮转)
python -m src.cli schedule --start 2026-09-17T09:00:00 --days 7 --existing-links 4 --out OUTPUT_DIR

# 5) 真实构建单个专题 (建议先设 GITHUB_TOKEN; 传真实链时自动 bind-pan)
set GITHUB_TOKEN=[GITHUB_TOKEN]
python -m src.cli build --topic py-office --out OUTPUT_DIR ^
  --pan-share-url [PAN_SHARE_URL] --pan-extract-code [PAN_EXTRACT_CODE]

# 6) 全部 4 个专题
python -m src.cli build --all --out OUTPUT_DIR

# 7) 生成当天复盘 JSON
python -m src.cli report --out OUTPUT_DIR --orders 7 --pan-new 3 --pan-saves 24 --pan-commission 33.6

# 8) 收益模型验算
python scripts/economics.py
```

`bind-pan` 会拒掉 `[PAN_SHARE_URL]` 这类占位值、非 http(s) URL、参数里带 `wx/qq/phone` 的链接；写回前重生成 `auto_reply.txt` 并过红线扫描。`schedule` 在有效链接达到 25 后自动把新槽切成「擦亮 / 衍生」，不再硬新增；长尾词按「专题自身出现轮次」轮转，避免 4 个专题 × 3 词时撞回同一组。

重建保活：`build` / `selftest` 覆盖旧包前会抢救旧 `_manifest.json` 的 `pan` 段与 `01` 文件里「## 买家高频咨询补充」之后的 FAQ，重建后原样回写，并在 manifest 里留 `rebuild_preserved`。所以每周追加更新不会把已绑定推广链和售后迭代内容删掉。`verify` 会额外打印体积未达标（500–2048 MB）的包清单。

离线回归已扩到 42 项：`python -m unittest discover -s tests -v`。

Windows 下 `python` 若不在 PATH，用 `py -3 -m src.cli ...`。所有产物落在 `--out` 指定目录，默认 `OUTPUT_DIR`。

## 产出结构

```
OUTPUT_DIR/
├── 2026持续更新_GitHub精选【Python办公自动化神器】合集/
│   ├── 00_项目清单与中文简介说明.md      三段中文场景导语 + Star / 摘要 / 原仓库 URL / 协议 / SHA-256
│   ├── 01_新手环境配置与国内镜像加速.txt  pip / npm / Maven 国内源 + FAQ
│   ├── 02_Windows免安装可执行程序包/      官方 Release .exe/.msi
│   ├── 03_精选开源项目源码合集/01_owner_repo/...  完整保留 LICENSE
│   └── _manifest.json                     机读清单, 含排除记录与网盘字段
├── listings/<topic-id>/
│   ├── xianyu_detail.md
│   ├── auto_reply.txt
│   └── listing_plan.json
├── reports/
│   ├── build_<utc>.json
│   ├── selftest_daily.json
│   ├── selftest_builds.json
│   ├── schedule_<date>.json          上架槽位 / 长尾词 / 链接数演进
│   ├── schedule_<date>.md            可照着操作的时间表
│   └── daily_<date>.json
└── cache/                              源码 tarball 与 Release 资产
```

## 合规闸（写死在代码里，绕不过去）

| 层 | 位置 | 判定 |
| --- | --- | --- |
| 仓库 | `screen_repo` | 关键词/topic 黑名单、协议 SPDX 白名单、star 与标识有效性 |
| 归档 | `has_license` | 真实打开 tar 找 LICENSE/COPYING，API 字段说谎也拦 |
| 资产 | `select_release_assets` | 仅 `.exe/.msi/.zip`，≤300MB，名称不含联系方式 |
| 解包 | `_safe_member` | 拒绝 `..`、绝对路径、符号链接、设备文件、2GB 总体积 |
| 文案 | `check_text` / `_assert_clean` | 零宽字符、微信/QQ/手机号/邮箱/二维码、强制诱导 App、"必须下载…才发货" |
| 声明 | `check_declaration` | 清单与详情页必须含"整理自 GitHub / 遵循原项目开源协议 / 所收费用仅为…" |
| 推广链 | `validate_share_url` / `bind` | 拒占位符、非 http(s)、联系方式型参数；写回前重扫发货文案 |

手机号正则加了前后非字母数字断言，SHA-256 摘要里偶然出现的 11 位数字不会被误判成站外引流。

自动发货文案只做温和引导："资源已整理存入网盘，因开源文件夹较大，建议保存至个人网盘后按需下载，内附中文部署清单"。

## 网盘推广接法

`_manifest.json` 的 `pan` 段预留 `share_url` / `extract_code` / `channel_reported`。真实流程：

1. 在任推邦 / 星子助推 / 洽立方申请夸克与百度网盘推广权限，绑定专用存储 UID 并完成渠道报备；
2. 上传 `2026持续更新_…合集/` 整目录（保持多级结构），生成**推广渠道**分享链接；
3. 正式回填用 `bind-pan --topic <id> --share-url <真实链> --extract-code <码>`；它会写入 `_manifest.json` 的 `pan` 段（`bound_at` / `channel_reported` / `settlement`）并原子重写 `auto_reply.txt`。`build` 同时传真实链也会自动走这一步；占位链只保留文案占位，不写 manifest。
4. `verify` 会打印「推广链绑定: N/M」，`schedule` 会把未绑定专题的槽位标 `[待补] 该专题尚未 bind-pan`；上架前逐个补齐。
5. 服务商后台 T+1 核对拉新与转存，转化率 < 5% 的链接淘汰。

环境变量：`GITHUB_TOKEN`、`PAN_PROMOTE_UID`、`XIANYU_AUTO_REPLY_PLUGIN`。缺值时脚本用占位符继续跑，不阻塞。模板见 [.env.example](.env.example)；每一项的含义、来源、填到哪、验收命令见 [docs/PREREQUISITES.md](docs/PREREQUISITES.md)。

## 红线复述

- 保留每个项目原 `LICENSE` 与作者链接，详情页统一声明"费用仅为整理服务费"；
- 对话框与自动发货文案不出现微信号、QQ 号、手机号、二维码；
- 不写"必须下载某 App 才能发货"；
- 抓取脚本过滤渗透测试 / 攻击 / 破解 / 翻墙代理类仓库；
- 不用接码平台、模拟器自刷网盘拉新佣金。

详见 [docs/ops-sop.md](docs/ops-sop.md)。
