# 全维度资产统计（all-asset-dashboard）

把「传统股票 & 基金」和「加密货币」放在一张表里看的个人资产仪表台：

- **你只维护份额**：`data/holdings.json` 里每个标的的 `shares` 是唯一人工输入
- **后台算市值**：`scripts/build.py` 抓价格 → 份额 × 价格 × 汇率 = 市值 → 占比、日变动、趋势
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
2. 拖入 `.xlsx / .xls / .csv` 持仓表，表头包含「项目名称 / 代码」+「持有数量」
3. 确认匹配结果 → 「应用」→「保存并计算」

### 方式 B：手工改份额

在 `admin.html` 表格里直接改「持有份额」，点「保存并计算」。

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

### 静态站点的写入限制

GitHub Pages 是纯静态托管，`admin.html` 无法直接写仓库。因此在线上保存时：

1. 点「下载 holdings.json」
2. 到仓库 `data/holdings.json` 覆盖上传（网页端可直接拖拽提交）
3. Actions 下一次构建（或手动 Run workflow）后生效

若想在线直接写入，把本仓库放到任意能跑 Python 的机器上，用 `scripts/server.py` 托管即可。

## 五、口径说明

- 市值 = 份额 × 最新价格 × 汇率；加密货币市值 = 数量 × 币价（USDT）× 汇率。
- 占比 = 标的市值 / 总资产；分组占比 = 传统合计 / 总资产、加密合计 / 总资产。
- 日变动 = Σ(标的市值 × 当日涨跌幅)；加密货币按相邻快照币价差计算，不含当日充提。
- 趋势图来自 `data/snapshots.json`：每天一条，脚本按日期覆盖同一天记录，不会重复累积。
- 场外基金（如 007466）用东方财富最新净值估值，非实时成交价。

免费行情源（腾讯 / 新浪 / 天天基金 / Yahoo / er-api）仅供个人研究，不得商用或再分发；数据准确性以官方披露为准。

## 六、已知限制

- 静态页面自身不能持久化写入，线上保存需下载 JSON 再上传（见上）。
- 加密货币日变动基于快照价差，若某币当日无前值则记为 0。
- 标的价格依赖免费源可用性；失败时该标的市值显示为空并保留 `price_source: 未取到`。
