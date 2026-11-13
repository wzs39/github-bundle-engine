# 开工前准备清单 · 需要你提供的东西

> 这份文档回答一个问题：**代码之外，还差什么才能跑起来、才能开始卖。**
> 引擎本身零依赖、零成本，`selftest` 全程离线、不需要下面任何一项；下面是「真实抓取 / 真实上架 / 真实结算」所需。
> 配一个自检脚本：`python scripts/check_prereqs.py`，它会按本文逐项打印「已就绪 / 待补」。

约定：所有具体值用 `[占位符]` 表示，**不要把真实 token、推广链、提取码、UID 写进仓库、Issue 或聊天记录**。仓库 `.gitignore` 已排除 `.env*`、`*.secret`、`_secrets/` 与 `OUTPUT_DIR/`。

---

## 0. 分三类看差距

| 类别 | 含义 | 数量 | 不做的后果 |
| --- | --- | ---: | --- |
| **A · 硬门槛** | 必须由你在外部平台申请/开通，代码无法代劳 | 5 | 无法真实抓取、无法上架、无法结算 |
| **B · 占位值** | 代码里留了槽位，按实际填值即可 | 3 | 功能降级（无镜像回退、无归属 UID、无主图） |
| **C · 平台人工动作** | 脚本产出「该做什么」，你在后台点 | 4 | 运营节奏跑不起来，但不影响代码闭环 |
| **D · 已具备** | 本机实测已就绪，无需再准备 | — | 见 §4，列出来免得重复确认 |

**最小可卖路径 = A1 + A2 + A3 + A4 + A5**。B 类可在跑通后补，C 类是日常运营动作。

---

## 1. A 类 · 硬门槛（5 项）

### A1 · GitHub Personal Access Token

| 项 | 内容 |
| --- | --- |
| 要什么 | 一个 classic 或 fine-grained PAT，**只需公开仓库只读权限**（`public_repo` / `Contents: read`），不需要写权限 |
| 为什么 | 未认证时 GitHub Search API 只有 **60 次/小时**，4 个专题各要搜索 + 逐仓库查 Release，一次 `build --all` 就可能撞限流；脚本虽会按 `X-RateLimit-Reset` 自动等待，但会拖到几十分钟 |
| 从哪拿 | GitHub → Settings → Developer settings → Personal access tokens → Generate new token |
| 填到哪 | 环境变量 `GITHUB_TOKEN`（或写入本地 `.env`，见 [.env.example](../.env.example)）。`check_prereqs.py` 与 `run_daily.ps1` 都会自动加载 `.env` |
| 现状 | **本机已就绪**：`.env` 已由 gh 登录态（wzs39）生成并完成验收。可选加固：另建一个只读（Contents: read）fine-grained PAT 替换，缩小凭据面 |
| 验收 | `python scripts/check_prereqs.py` → A1 显示 OK |

### A2 · 网盘推广渠道报备 + 真实推广链

| 项 | 内容 |
| --- | --- |
| 要什么 | ① 在任推邦 / 星子助推 / 洽立方**任选其一**注册并通过一级服务商审核；② 申请**夸克网盘**（主力高单价）+ **百度网盘**（覆盖存量用户）推广权限；③ 绑定专用存储网盘 UID 并完成渠道报备；④ 为每个专题目录生成**推广渠道**分享链接 + 提取码（各 1 组，共 9 组） |
| 为什么 | 普通分享链不触发 T+1 拉新佣金（约 7–12 元/新用户）与转存收益（约 0.3–0.5 元/次）；`bind-pan` 会明确拒掉占位符和非 http(s) 链，就是为了不让你误用普通链 |
| 从哪拿 | 服务商后台 → 推广管理 → 夸克/百度网盘 → 生成推广链接；**必须是已报备 UID 名下生成的链** |
| 填到哪 | 逐个执行 `python -m src.cli bind-pan --topic <id> --share-url <真实链> --extract-code <码> --promote-uid <UID> --out OUTPUT_DIR`，`<id>` 取 `local-ai` / `py-office` / `grad-project` / `portfolio` / `kaoyan` / `gaokao` / `english` / `study-software` / `hot-oss` |
| 验收 | `python -m src.cli verify --out OUTPUT_DIR` 打印 `推广链绑定: 9/9`；排程表 `[待补]` 标记消失 |

> 顺序提示：先 `build --all` 产出真实目录 → 上传网盘 → 生成推广链 → 再 `bind-pan`。重建包时引擎会自动保活已有的 `pan` 段，不会把绑定冲掉。

### A3 · 真实抓取一次（不是夹具）

| 项 | 内容 |
| --- | --- |
| 要什么 | 跑一次 `python -m src.cli build --all --out OUTPUT_DIR`（或直接 `daily` 一条龙） |
| 为什么 | 夹具包 `package_mb ≈ 0.01`；策略书要求单专题 500MB–2GB 才有干货感、才能促使买家转存 |
| 从哪拿 | 依赖 A1；`download_mirrors` 见 B1 |
| 填到哪 | 直接跑命令；产物覆盖 `OUTPUT_DIR/2026持续更新_*合集/`。注意磁盘需数 GB，日志/缓存都在 OUTPUT_DIR 下 |
| 现状 | **链路已验证**：kaoyan 真实构建通过（搜索 → 合规闸排除 17 个 → 真实下载 10 仓库 → 370 MB 成包） |
| 验收 | `verify` 的体积清单变短或为空；`_manifest.json` 里 `repos[].full_name` 是真实 GitHub 仓库。体积门槛已支持专题级覆盖：考研 150 / 高考 100 / 英语 150 / 热门开源 300 MB，纯笔记专题不再与 500MB 全局下限死磕 |

### A4 · 闲鱼独立账号 + 自动发货

| 项 | 内容 |
| --- | --- |
| 要什么 | ① 1 个**与日常实物买卖主力号严格分离**的闲鱼账号，完成实名认证 + 芝麻信用授权；② 前 2 天每天浏览效率工具/源码类商品 15 分钟养基础权重；③ 闲鱼网页版后台自动回复或低成本自动发货插件，实现「付款 → 3 秒内发网盘链接+提取码」 |
| 为什么 | 前端 0.99–9.9 元即时到账靠自动发货；账号混用会把日常号一并暴露在风控里 |
| 从哪拿 | 闲鱼 App / 网页版后台；插件按你选的方案自备 |
| 填到哪 | 插件配置里粘 `OUTPUT_DIR/listings/<id>/auto_reply.txt` 全文；环境变量 `XIANYU_AUTO_REPLY_PLUGIN` 记插件标识 |
| 验收 | 自己下一单测试：付款后 3 秒内收到含真实链接与提取码的消息，且文案无站外联系方式 |

### A5 · 网盘整目录上传

| 项 | 内容 |
| --- | --- |
| 要什么 | 把 `OUTPUT_DIR/2026持续更新_GitHub精选【…】合集/` **整目录**（4 个）上传网盘，保持 `00 / 01 / 02 / 03` 多级结构 |
| 为什么 | 策略书明确不压成单个死压缩包：多级目录可预览 → 买家一键转存 → 触发 App 拉新与转存收益 |
| 从哪拿 | A3 的产物 |
| 填到哪 | 网盘客户端，与 A2 的推广 UID 同一个存储账号 |
| 验收 | 手机端打开推广链能看到四层目录；每周往同一文件夹追加新项目，不换链接，激活老买家二次转存 |

---

## 2. B 类 · 占位值（3 项，跑通后补）

| # | 占位符 | 位置 | 现状 | 要填什么 | 影响 |
| --- | --- | --- | --- | --- | --- |
| B1 | `[MIRROR_PREFIX_1]` / `[MIRROR_PREFIX_2]` | [config/settings.json](../config/settings.json) 的 `download_mirrors` | 是占位串，`gh_client` 会过滤 `[` 开头的值，等于**没有回退** | 填真实可用的 codeload 加速前缀（形如 `https://<host>/https://github.com` 的拼接基址），按需 1–2 个 | 直连不稳时源码下载直接失败；填了才逐个回退 |
| B2 | `[PAN_PROMOTE_UID]` | 环境变量 `PAN_PROMOTE_UID` + `_manifest.json` 的 `pan.promote_uid` | 占位 | 已报备的专用存储网盘 UID | 佣金归属核对、服务商后台对账 |
| B3 | 主图素材 | `OUTPUT_DIR/listings/<id>/listing_plan.json` 的 `main_image` | 只是文字规格「目录截图 + 痛点大字」 | 按规格出 1 张主图/专题，爆款另做 1–2 张换封面衍生 | 曝光与点击率；删换链接时靠它 |

B1 填法示例（改成你的实际前缀，别照抄）：

```json
"download_mirrors": ["https://[MIRROR_HOST]/https://github.com"]
```

脚本会把镜像前缀与原始 URL 拼成候选逐个尝试，全失败才报错并保留具体原因。

---

## 3. C 类 · 平台侧人工动作（4 项，脚本只给指令）

这几项不是「要准备的材料」，是每天 90 分钟 SOP 里需要你在后台点的地方。脚本产出「该做什么」，不代点。

| # | 动作 | 脚本产出 | 你在哪做 | 判据 |
| --- | --- | --- | --- | --- |
| C1 | 全店擦亮；曝光<100 且零「想要」的链接删除重发 | `daily_<date>.json` 的 `actions`、`listing_plan.json` 的 `retire_rule` | 闲鱼后台 | 前 48 小时数据 |
| C2 | 出单好的链接做 1–2 个长尾衍生链接 | `schedule` 的 `derivative` 槽 + `derivative_links` | 闲鱼后台，换封面图重发 | 有效链接达 25 后不再硬新增 |
| C3 | 核对 T+1 拉新/转存，淘汰转化率<5% 的链接 | `report` 的 `pan.settlement` / `actions` | 服务商后台 | T+1 真实数据 |
| C4 | 高频咨询补进 `01` 文件并覆盖网盘旧版 | `01_新手环境配置与国内镜像加速.txt` 已留 `## 买家高频咨询补充` 锚点，重建自动保活 | 写进该段落 | 每周追加 |

另：`economics.py` 的 40–120 元/日是按策略书参数做的**模型推演**，不是实测收益。里程碑 ①（首笔成交 + 首笔佣金到账）、②（20 链接 / 日均 5–10 单）、③（被动现金流）都还没开始验证。

---

## 4. D 类 · 已具备（本机实测，无需准备）

| 项 | 实测值 |
| --- | --- |
| Python | 3.13.1（`python --version`） |
| git | 2.51.2.windows.1，身份 `overthinkknow <wang391435@qq.com>` |
| GitHub CLI | 已安装并登录，账号 `wzs39`（`gh api user --jq .login`） |
| 仓库 | https://github.com/wzs39/github-bundle-engine ，公开，MIT，默认分支 `main` |
| 代码 | 56 项离线回归 OK（含热点发现 / 盈利核算 / 合规词边界） |
| 离线全链路 | trends(实网 11/12 源) → selftest 9 专题 → bind-pan ×9 → schedule → profit → verify 全部 RC=0 |
| 热点发现 | 12 源 8 向垂直（AI/技能/热门项目/考研/高考/英语/学习软件/热门开源），`daily` 一条龙可挂计划任务 |

也就是说：**现在就可以跑 `selftest` 和 `schedule`，一分钱不花、一样东西都不用准备。**

---

## 5. 最小收口顺序

```bash
# ① 零准备：先把离线闭环跑一遍（可选但建议）
python -m src.cli selftest --all-topics --out OUTPUT_DIR
python scripts/check_prereqs.py                      # 看还差哪几项

# ② A1 已就绪；B1 可选，直接真实抓取（或 daily 一条龙含热点发现）
python -m src.cli build --all --out OUTPUT_DIR

# ③ 备齐 A2 + A5 后，逐个绑定推广链（占位符会被拒绝）
python -m src.cli bind-pan --topic local-ai     --share-url [真实链] --extract-code [码] --promote-uid [UID] --out OUTPUT_DIR
python -m src.cli bind-pan --topic py-office    --share-url [真实链] --extract-code [码] --promote-uid [UID] --out OUTPUT_DIR
python -m src.cli bind-pan --topic grad-project --share-url [真实链] --extract-code [码] --promote-uid [UID] --out OUTPUT_DIR
python -m src.cli bind-pan --topic portfolio    --share-url [真实链] --extract-code [码] --promote-uid [UID] --out OUTPUT_DIR

# ④ 发货前最后一道闸：绑定 4/4 且体积清单为空
python -m src.cli verify --out OUTPUT_DIR

# ⑤ 备齐 A4 后照排程表上架
python -m src.cli schedule --days 7 --existing-links 4 --out OUTPUT_DIR
```

---

## 6. 给我什么格式就行

按下面这份回我就够了，其余我自动补齐并复跑验收：

```
GITHUB_TOKEN=[已就绪, 来自 gh 登录态]
PAN_PROMOTE_UID=[...]
MIRROR_PREFIX_1=[...]
XIANYU_AUTO_REPLY_PLUGIN=[...]

local-ai       分享链=[...] 提取码=[...]
py-office      分享链=[...] 提取码=[...]
grad-project   分享链=[...] 提取码=[...]
portfolio      分享链=[...] 提取码=[...]
kaoyan         分享链=[...] 提取码=[...]
gaokao         分享链=[...] 提取码=[...]
english        分享链=[...] 提取码=[...]
study-software 分享链=[...] 提取码=[...]
hot-oss        分享链=[...] 提取码=[...]
```

或者自己写进本地 `.env`（模板见 [.env.example](../.env.example)），不用发给我。`gh` 已登录、`git` 身份已配、仓库已推，这几样不用再给。

**别把真实值贴进公开仓库 / Issue / README**——仓库是 public 的。
