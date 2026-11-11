# 全维度资产统计（all-asset-dashboard）

把「传统股票 & 基金」和「加密货币」放在一张表里看的个人资产仪表台：

- **你只维护份额和成本价**：`data/holdings.json` 里每个标的的 `shares`（持有份额）与 `cost_price`（每份持仓成本价）是唯一人工输入
- **后台算市值与盈亏**：`scripts/build.py` 抓价格 → 份额 × 价格 × 汇率 = 市值；市值 − 份额 × 成本价 × 汇率 = 浮动盈亏 → 收益率、占比、日变动、趋势
- **传统标的价格**：优先取「全球资产仪表台」（index-fund-dashboard）已抓好的行情，缺失时回退腾讯实时 / 天天基金 / Yahoo
- **加密货币**：直接读取「加密货币资产仪表台」（bitget-pnl-dashboard）最新快照，现货 + 理财合并
- **前端 page**：`index.html` 读 `data/dashboard.json` 渲染，展示传统 vs 加密的资产占比

## 页面与入口

| 入口 | 说明 |
|---|---|
| `index.html` | 资产仪表台：KPI、资产占比、持仓明细、总资产趋势、数据来源 |
| `admin.html` | 份额维护后台：上传持仓表 / 手工改份额 / 新增标的 / 保存并计算 |
| `scripts/build.py` | 后台计算脚本（GitHub Actions 每日运行） |
| `scripts/server.py` | 本地后台服务（带写入接口，可直接保存并重建） |

## 一、数据流

```
data/holdings.json ─┐
                    ├─ scripts/build.py ─→ data/dashboard.json ─→ index.html
全球资产仪表台 ─────┤                        └→ data/snapshots.json（每日累积，供趋势图）
加密货币资产仪表台 ─┘
```

抓取优先级（`scripts/sources.py`）：

1. `https://978912280-jpg.github.io/index-fund-dashboard/data/dashboard.json`（按标的代码命中即用）
2. 腾讯实时行情 `qt.gtimg.cn`（A 股 / ETF / 美股）
3. 东方财富基金接口（场外基金净值，如 007466；失败回退天天基金 fundgz）
4. Yahoo chart（海外兜底）

汇率 USD/USDT → CNY 取 `open.er-api.com`，失败时用 `holdings.json` 的 `usdcny_fallback`。

加密货币：读取 `https://978912280-jpg.github.io/bitget-pnl-dashboard/data/history.json` 最新快照的 `byCoin`（现货 + 理财合并），按币种汇总数量 × 价格 = USDT 市值，日变动用相邻两个快照的币价差计算（不含出入金）。

## 二、日常怎么用（只改份额）

### 方式 A：页面上传持仓表（推荐）

1. 打开 `admin.html`
2. 拖入 `.xlsx / .xls / .csv` 持仓表，表头包含「项目名称 / 代码」+「持有数量」，可选「成本价 / 累计投入成本」（有累计投入成本时自动按 成本 ÷ 份额 折算成本价）
3. 确认匹配结果 → 「应用」→「保存并计算」

### 方式 B：手工改份额

在 `admin.html` 表格里直接改「持有份额」和「成本价」，点「保存并计算」。

### 方式 C：直接编辑 JSON

编辑 `data/holdings.json` 的 `shares` 字段，提交后由 Actions 重建。

> 加密货币不需要填份额：它每天从「加密货币资产仪表台」自动同步。

## 三、本地运行

```bash
python3 scripts/build.py          # 抓价格并生成 data/dashboard.json
python3 scripts/server.py         # http://127.0.0.1:8787 ，带写入接口
# 或只做静态预览：
python3 -m http.server 8080
```

`server.py` 提供的接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/holdings` | 读取份额配置 |
| POST | `/api/holdings` | 保存份额配置（自动备份到 `data/backups/`，随后重建） |
| POST | `/api/rebuild` | 只重新抓价重建 |

> 接口无鉴权，默认只监听 `127.0.0.1`；不要暴露到公网。

## 四、部署到 GitHub Pages

1. 推送本目录到仓库（默认分支 `main`）。
2. 仓库 **Settings → Pages → Build and deployment → Source** 选 **GitHub Actions**。
3. 工作流 `.github/workflows/daily.yml` 每天 08:10（北京时间，UTC `10 0 * * *`）运行：
   抓价 → 重建 → 提交 `data/dashboard.json` 与 `data/snapshots.json` → 部署 Pages。
4. 也可在 Actions 页面手动 **Run workflow**。

站点地址：`https://<用户名>.github.io/all-asset-dashboard/`

### 三种保存方式

| 方式 | 适用 | 做什么 |
|---|---|---|
| **GitHub 直连（推荐）** | 线上 Pages 页面 | 在 `admin.html` 填一个本仓库 Token，「保存并计算」会自动 commit `data/holdings.json` → 触发 Actions 构建 → 页面自动刷新 |
| 下载 JSON 上传 | 不想在浏览器存 Token | 下载 `holdings.json`，到仓库覆盖 `data/holdings.json`，等下次构建 |
| 本地后台 | 在自己电脑上跑 | `python3 scripts/server.py`，直接写入并重建 |

**Token 怎么给**：GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → 只选本仓库 →
权限勾 `Contents: Read and write` 与 `Actions: Read and write` → 生成后粘贴到后台页面。

- Token 只保存在你本机浏览器（勾选「记住到本机浏览器」时）；不勾选则关闭页面即失效。
- 缺 `Actions` 权限也能提交文件，只是需要等每日定时构建；页面会明确提示。
- 公用电脑上不要勾选「记住」；用完点「清除 Token」。

## 五、口径说明

- 市值 = 份额 × 最新价格 × 汇率；加密货币市值 = 数量 × 币价（USDT）× 汇率。
- 浮动盈亏 = 市值 − 持仓成本，持仓成本 = 份额 × 成本价 × 汇率（成本价与现价同币种）；收益率 = 浮动盈亏 / 持仓成本。
- 成本价未填（0）的标的只算市值不算盈亏；加密货币盈亏沿用「加密货币资产仪表台」的净入金口径真实盈亏，与传统的成本价口径分开列示。
- 占比 = 标的市值 / 总资产；分组占比 = 传统合计 / 总资产、加密合计 / 总资产。
- 日变动 = Σ(标的市值 × 当日涨跌幅)；加密货币按相邻快照币价差计算，不含当日充提。
- 趋势图来自 `data/snapshots.json`：每天一条，脚本按日期覆盖同一天记录，不会重复累积。
- 场外基金（如 007466）用东方财富最新净值估值，非实时成交价。

免费行情源（腾讯 / 新浪 / 天天基金 / Yahoo / er-api）仅供个人研究，不得商用或再分发；数据准确性以官方披露为准。

## 六、已知限制

- 静态页面自身不能持久化写入，线上保存需下载 JSON 再上传（见上）。
- 加密货币日变动基于快照价差，若某币当日无前值则记为 0。
- 标的价格依赖免费源可用性；失败时该标的市值显示为空并保留 `price_source: 未取到`。

## 定时触发（cron-job.org，不依赖 GitHub schedule）

GitHub 自带的 `schedule` 经常延迟甚至漏跑（实测有延迟数小时的情况），因此本仓库**已移除 `schedule`**，只保留两个触发入口：

| 入口 | 用途 |
|---|---|
| `workflow_dispatch` | 手动点「Run workflow」；后台「立即抓取最新价格」按钮；cron-job.org 定时调用 |
| `repository_dispatch` (`event_type=daily`) | 备用入口，也可被外部服务调用 |

### 在 cron-job.org 建一个 Job

- **标题**：全维度资产统计 · 每日构建
- **URL**：`https://api.github.com/repos/978912280-jpg/all-asset-dashboard/actions/workflows/daily.yml/dispatches`
- **请求方式**：`POST`
- **执行计划**：每天 `08:15`，时区 `Asia/Shanghai`（必须在加密仪表台 07:00 快照之后）
- **请求头**：
  - `Authorization: Bearer <你的 GitHub Token>`
  - `Accept: application/vnd.github+json`
  - `Content-Type: application/json`
- **请求体**：`{"ref":"main"}`
- **成功判据**：GitHub 返回 `204 No Content`（cron-job.org 里把「成功状态码」设为 204）

Token 建议单独建一个 **fine-grained PAT**，只授权本仓库、只勾 **Actions: Read and write**，不要复用其他项目的全权限 token。Token 会存在 cron-job.org 服务器上，属于必要风险，可随时吊销重建。

调用成功后，构建约 1 分钟完成并自动部署 Pages；数据是否真的更新，看仓库最新提交是否为 `chore(data): 更新资产快照 <日期>`。

## 版本号规则

- 首页顶部与页脚显示的 `v1.0.x` 取自 `data/holdings.json` 的 `meta.version`。
- 每次发布新的页面改动，版本号 **+0.0.1**；分位到 10 进 1：`1.0.9 → 1.1.0`，`1.9.9 → 2.0.0`。
- 发布时必须同时改三处，保持一致：`data/holdings.json` 的 `meta.version`、`scripts/build.py` 的 `PAGE_VERSION`、`index.html`/`admin.html` 的 `data-page-version` 与 `css/js?v=`。
- `PAGE_VERSION` 同时充当缓存键：页面加载时若发现 HTML 里的版本与 `dashboard.json` 的 `meta.page_version` 不一致，会自动带 `?pv=<版本>` 重新拉取，避免 Safari 缓存旧页面。

## 当日浮动收益的算法与份额滞后

- 当日浮动收益 = **上一份快照里的份额 × 当日价差 × 汇率**，快照会记录每个标的的 `shares` 与 `price`。
- 好处：如果某几天没更新份额、之后才补录，**历史日期上的数字不会被改写**；补录当天新增的份额按收盘价买入处理，不计入当日盈亏。
- 只有在找不到更早快照时，才退化为「今日份额 × 当日涨跌幅」（`day_basis = pct`）。
- 份额新鲜度：`dashboard.json` 的 `meta.shares_age_days` 取自 `holdings.json` 的 `meta.updated_at`；超过 7 天首页会出现提醒，提示核对是否有买卖/定投未录入。
