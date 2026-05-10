# A 股行业 ETF 轮动策略系统 v0.1

这是一个轻量级、可解释、低频调用的 A 股行业 ETF 轮动框架。v0.1 的目标不是追求最高收益，而是先把数据、缓存、降级、信号、回测和输出跑通，方便后续迭代。

## 核心思想

系统采用三层框架：

```text
日K线：决定行业方向、趋势状态、轮动排序和目标仓位；
基本面：作为行业偏好修正和风险过滤，不单独触发买入；
60分钟K线：只做执行过滤，避免短线走弱或追高。
```

日K负责行业选择，是因为行业轮动通常不是日内噪声驱动，而更接近周度到月度级别的趋势和相对强弱变化。基本面只做辅助，是为了避免“低估值抄底”或“财务好但价格持续走弱”的纪律失效。60分钟只做执行过滤，是为了在已经决定目标行业后，减少追高和短线走弱时的买入。

## Tushare token

不要把 token 写进代码。程序只从环境变量读取：

```powershell
$env:TUSHARE_TOKEN="你的token"
```

如果没有读取到 `TUSHARE_TOKEN`，权限检测会直接给出清晰报错；回测在没有 Tushare 权限时会尝试读取本地 CSV，仍无数据才报错。

如果本机或执行环境封锁了 Tushare SDK 默认的 HTTP 地址，可以临时覆盖 API 地址：

```powershell
$env:TUSHARE_API_URL="https://api.waditu.com/dataapi"
```

也可以在 `config.yaml` 的 `data.tushare_api_url` 中修改。Tushare Python SDK 1.4.x 默认请求 `http://api.waditu.com/dataapi`，部分受限沙箱、防火墙或公司网络会拦截 HTTP 80 端口，表现为 `WinError 10013` 或连接失败。

如果你本机 VPN/代理端口是 7890，可以设置：

```powershell
$env:TUSHARE_PROXY_URL="http://127.0.0.1:7890"
```

本项目也在 `config.yaml` 中提供了 `data.proxy_url`，默认按本机 7890 代理配置。`requests` 会通过 `HTTP_PROXY` / `HTTPS_PROXY` 走代理。

## 运行权限检测

```bash
python scripts/check_tushare_access.py
```

Windows 用户也可以直接运行：

```text
scripts/run_tushare_check_local.bat
```

这个批处理会在你自己的 Windows 终端里运行，不走 Codex 沙箱；如果当前终端没有 `TUSHARE_TOKEN`，它会临时提示输入，不会写入代码文件。

如果网络不稳定，建议先逐只预取 ETF 日线：

```text
scripts/fetch_etf_daily_local.bat
```

它会把每只 ETF 单独缓存到 `data/local_csv/etf_daily_代码.csv`，并写出 `fetch_etf_daily_manifest.csv`。下次再运行时，已成功缓存的 ETF 会自动跳过，适合低权限、低频调用和断点续跑。

如果希望让 Codex 后续继续驱动数据获取，可以启动本机桥接服务：

```text
scripts/start_tushare_bridge_local.bat
```

保持窗口打开后，Codex 可以访问本机 `http://127.0.0.1:8765`，调用桥接服务取数并缓存。这样只需要你手动启动一次服务，后续取数、回测、检查缓存都可以继续在 Codex 里推进。

默认优先使用缓存。需要重新请求 Tushare 时：

```bash
python scripts/check_tushare_access.py --refresh
```

检测范围包括 ETF 日线、ETF 60分钟、指数日线、基金基础信息、`daily_basic`、`index_weight`、`fina_indicator`、`express`、申万行业相关接口。某个接口权限不足不会导致程序崩溃，会输出降级建议。

### 网络故障排查

如果在 Codex 沙箱里看到类似：

```text
WinError 10013 以一种访问权限不允许的方式做了一个访问套接字的尝试
```

这通常不是 token 或积分不足，而是当前执行环境阻止了外网 socket。处理方式：

1. 在 Codex 弹出的权限请求中允许脚本联网；
2. 或在你自己的 PowerShell/Anaconda Prompt 里运行同一条命令；
3. 或设置 `TUSHARE_API_URL` 为可访问的 HTTPS/代理地址；
4. 如果仍然不通，先把 CSV 放入 `data/local_csv/`，主回测会走本地数据。

## 运行回测

```bash
python scripts/run_backtest.py
```

或：

```bash
python main.py
```

除非显式传入 `--refresh`，否则会优先读取 `data/` 缓存，避免重复请求 Tushare。ETF 日线不可用时，可把本地 CSV 放在：

```text
data/local_csv/etf_daily_512000.SH.csv
```

CSV 至少需要包含 `trade_date, open, high, low, close`，建议包含 `amount` 或 `volume`。如果没有成交额字段，流动性过滤只能用成交量近似，无法严格比较不同 ETF 的真实交易金额。

## ETF 池

ETF 池在 `config.yaml` 手工维护，每个 ETF 包含代码、名称、主题、跟踪指数、申万行业映射和是否启用基本面。程序不会假设所有 ETF 都可用，无法获取日线数据的 ETF 会自动跳过。

## 日线因子

流动性过滤：过去 20 个交易日日均成交额低于阈值的 ETF 剔除。

趋势过滤：默认要求 `close > MA60` 且 `MA20 > MA60`。

技术面得分使用横截面 z-score：

```text
0.25 * 20日收益率
+ 0.35 * 60日收益率
+ 0.20 * 120日收益率
- 0.10 * 20日波动率
- 0.10 * 60日最大回撤
- 0.10 * 相对20日均线偏离
```

这样做是为了避免直接把不同量纲的原始数值相加。

## 市场环境过滤

优先使用沪深300等指数：指数收盘价高于 120 日均线时允许做多，否则空仓。指数不可用时，使用 ETF 池市场宽度降级：

```text
强势ETF占比 < 30%：空仓
30% 到 50%：最多半仓
>= 50%：允许满仓
```

## 基本面模块

v0.1 的基本面模块在低权限环境下默认使用 `config.yaml` 的手工行业评分作为降级方案。它只修正综合得分，不会单独触发买入。

估值因子未来应使用行业或指数自身过去三年的 PE/PB 分位，而不是直接跨行业比较。原因是银行、医药、半导体等行业的合理估值中枢天然不同，直接比较 PE/PB 会把行业结构差异误当成便宜或昂贵。

财务数据必须按公告日期 `ann_date` 生效，避免未来函数。v0.1 暂不默认启用严格 point-in-time 财务因子；等确认 `index_weight`、行业成分、`fina_indicator` 等权限后，再替换当前手工评分。

## 60分钟模块

`src/features_intraday.py` 已保留接口，但 `config.yaml` 默认关闭 `use_intraday`。原因是周度调仓要严格保证只能使用调仓时点前已完成的 60分钟 K 线；如果权限或时间对齐不可靠，宁可关闭，也不引入未来函数。

## 输出文件

回测输出到 `outputs/`：

```text
equity_curve.csv
trades.csv
positions.csv
performance_summary.csv
equity_curve.png
drawdown.png
weekly_ranking.csv
fundamental_scores.csv
combined_scores.csv
```

`weekly_ranking.csv` 包含日期、ETF、主题、技术面得分、基本面得分、综合得分、流动性/趋势/估值/市场/60分钟过滤、最终是否入选和目标仓位等信息，便于逐周复查。

## 当前局限

v0.1 不做机器学习、不做参数寻优、不做高频交易、不使用杠杆或融券。基本面目前是低权限安全降级版本，60分钟执行过滤默认关闭。回测成交按配置的开盘价或收盘价近似执行，未模拟真实盘口冲击。

## 后续迭代

可以在不破坏框架的前提下逐步加入：严格 point-in-time 财务因子、指数成分加权估值、行业成分替代、交易日历、60分钟时间对齐、训练集/测试集参数评估、更多风险控制和更细的交易成本模型。参数优化必须单独做样本外验证，避免数据挖掘偏差。

## 已知排障记录

本项目在 Codex 沙箱中访问 Tushare 时，如果直接请求外网出现 `WinError 10013`，优先检查本机代理端口。当前配置默认使用：

```yaml
proxy_url: "http://127.0.0.1:7890"
```

只要本机 VPN/代理开启，脚本会自动设置 `HTTP_PROXY` 和 `HTTPS_PROXY`，通过 7890 访问 Tushare。

Tushare `fund_daily.amount` 常见单位是“千元”，而策略的 `liquidity_threshold` 使用“元”。当前默认配置为：

```yaml
amount_unit: "thousand_yuan"
```

程序会先换算为“元”再做流动性过滤。如果本地 CSV 的 `amount` 已经是“元”，请改成：

```yaml
amount_unit: "yuan"
```
