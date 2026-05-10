# 量化小白代码导读：v0.4 ETF 轮动系统

这份文档的目标不是把每一行代码翻译成中文，而是帮你建立一个能读懂、能修改、能继续迭代的代码地图。你只需要有 Python 基础，暂时不熟悉 pandas、回测、因子、调仓也没关系。

建议阅读顺序：

1. 先看“基础知识补充”，把常见概念扫一遍。
2. 再看“整体运行链路”，知道程序从哪里开始、数据怎么流动。
3. 最后按文件逐个读代码，遇到不懂的函数再回到基础知识部分查。

## 1. 你需要先补的基础知识

### 1.1 pandas 的 DataFrame 和 Series

本项目大量使用 pandas。

你可以把它们理解成：

| 对象 | 类比 | 例子 |
| --- | --- | --- |
| `DataFrame` | 一张 Excel 表 | ETF 日线行情表 |
| `Series` | Excel 表中的一列 | `close` 收盘价 |

常见写法：

```python
df["close"]
```

意思是取出 `df` 这张表里的 `close` 列。

```python
df[df["close"] > df["ma60"]]
```

意思是筛选出收盘价高于 60 日均线的行。

```python
df.copy()
```

意思是复制一份表，避免直接改坏原始数据。

### 1.2 时间序列和 rolling

量化里最常见的是“按时间排列的数据”，比如每天的 ETF 收盘价。

```python
out["ma60"] = out["close"].rolling(60).mean()
```

含义：

```text
对 close 这一列，每 60 个交易日算一次平均值。
结果就是 60 日均线。
```

再比如：

```python
out["ret_60"] = out["close"].pct_change(60)
```

含义：

```text
今天收盘价 / 60 个交易日前收盘价 - 1
也就是近 60 日收益率。
```

### 1.3 截面比较

时间序列是“同一只 ETF 在不同日期之间比较”。

截面比较是“同一天，不同 ETF 之间比较”。

本策略的风格内轮动就是截面比较：

```text
在同一个调仓日：
半导体 ETF、芯片 ETF、人工智能 ETF、医药 ETF ...
谁的成长风格得分最高？
```

### 1.4 z-score 标准化

不同因子单位不一样：

- 收益率可能是 `0.12`
- 成交额可能是 `80000000`
- 波动率可能是 `0.25`

如果直接相加，成交额会压倒一切。

所以项目里用 z-score：

```python
z = (x - 平均值) / 标准差
```

在代码里是：

```python
safe_zscore(values)
```

它把不同单位的因子变成“相对同组 ETF 高还是低”的可比数值。

### 1.5 因子和权重

因子就是一个用于排序或过滤的指标。

比如：

```text
ret_60 = 近 60 日收益率
vol_20 = 近 20 日波动率
dividend_spread = 股息率 - 10 年国债收益率
```

权重就是它在综合得分里的重要程度。

```yaml
ret_60: 0.25
vol_20: -0.10
```

正权重表示越高越好，负权重表示越高越差。

### 1.6 回测

回测就是把策略放到历史数据里模拟运行。

本项目的回测流程是：

```text
每天更新账户净值
每两周计算一次信号
下一个交易日执行买卖
扣手续费
记录持仓和交易
最后输出报告
```

注意：回测不是预测未来，只是检查策略规则在历史中表现如何。

### 1.7 未来函数

未来函数是量化里非常重要的坑。

错误例子：

```text
用 2025 年年报数据去决定 2025 年 1 月是否买入。
```

这相当于在历史中“偷看未来”。

本项目目前对财务数据比较谨慎，v0.4 主要使用估值、股息率、市场交易数据，避免在财报 point-in-time 没完全做好前大量使用财务成长数据。

### 1.8 缓存

Tushare 有权限和频率限制，所以项目会把请求结果存到 `data/`：

```text
第一次：请求 Tushare -> 保存 CSV
以后：直接读本地 CSV
```

核心好处：

- 少打 API
- 避免限频
- 回测更快
- 结果更容易复现

## 2. 项目整体运行链路

最常用命令是：

```bash
python scripts/run_backtest.py
```

整体流程如下：

```text
scripts/run_backtest.py
  -> 读取 config.yaml
  -> 读取 ETF 池
  -> 用 DataClient 获取 ETF 日线和基准指数
  -> run_backtest()
      -> prepare_features()
      -> 计算日线因子
      -> 计算基本面和红利因子
      -> 计算市场状态和融资风险
      -> 每两周 build_weekly_ranking()
      -> 根据目标仓位执行买卖
      -> 记录净值、交易、持仓
  -> save_outputs()
      -> 输出 CSV、图片、Markdown 报告
```

你可以把整个系统想成一条流水线：

```text
配置 -> 数据 -> 特征 -> 市场状态 -> 风格内打分 -> 调仓 -> 回测结果 -> 报告
```

## 3. 配置文件：config.yaml

`config.yaml` 是策略的控制面板。

它主要分四块：

| 区域 | 作用 |
| --- | --- |
| `data` | 数据起止日期、缓存目录、Tushare 代理、基准指数 |
| `backtest` | 初始资金、手续费、调仓频率、执行价格 |
| `strategy` | 市场状态仓位、风格内因子权重、过滤参数 |
| `etf_universe` | ETF 池，包含代码、名称、主题、风格、行业映射 |

如果你想改策略，优先改 `config.yaml`，不要一上来改 Python 代码。

例如调仓频率：

```yaml
rebalance_frequency: "biweekly"
```

例如成长池因子：

```yaml
growth_factors:
  ret_60: 0.25
  relative_ret_60: 0.15
  vol_20: -0.10
```

这表示：

```text
成长池重视 60 日动量和相对沪深300强度，
同时惩罚高波动。
```

## 4. 入口脚本：main.py 和 scripts/run_backtest.py

### 4.1 main.py

`main.py` 很短：

```python
from scripts.run_backtest import main

if __name__ == "__main__":
    main()
```

意思是：

```text
如果你运行 python main.py，
它其实会调用 scripts/run_backtest.py 里的 main()。
```

### 4.2 scripts/run_backtest.py

这是主回测入口。

关键步骤：

1. 用 `argparse` 读取命令行参数。
2. 用 `load_config()` 读取 `config.yaml`。
3. 用 `load_universe()` 读取 ETF 池。
4. 创建 `DataClient`。
5. 循环获取每只 ETF 日线。
6. 获取沪深300基准。
7. 调用 `run_backtest()`。
8. 调用 `save_outputs()`。

你可以重点理解这段伪代码：

```python
config = load_config(args.config)
universe = load_universe(config)
client = DataClient(config, refresh=args.refresh)

price_data = {}
for each ETF in universe:
    df = client.get_etf_daily(...)
    price_data[ETF代码] = df

benchmark = client.get_index_daily(...)
result = run_backtest(price_data, universe, benchmark, config)
save_outputs(result, config)
```

这里的 `price_data` 是一个字典：

```python
{
    "512000.SH": 券商ETF日线表,
    "512800.SH": 银行ETF日线表,
    ...
}
```

## 5. 工具函数：src/utils.py

这个文件放的是到处会用的小工具。

### 5.1 load_config()

读取 YAML 配置文件：

```python
with config_path.open("r", encoding="utf-8") as f:
    return yaml.safe_load(f)
```

返回的是 Python 字典。

例如：

```python
config["backtest"]["commission_rate"]
```

就能拿到手续费。

### 5.2 ensure_dir()

确保某个目录存在。

如果 `outputs/` 不存在，它会自动创建。

### 5.3 get_tushare_token()

从环境变量读取 `TUSHARE_TOKEN`。

这很重要：token 不能硬编码在代码里。

### 5.4 normalize_trade_date()

把 `trade_date` 转成 pandas 能识别的日期，并排序。

量化数据里日期格式经常不统一，所以这一步很常见。

### 5.5 safe_zscore()

安全版 z-score。

如果标准差是 0，普通 z-score 会除以 0；这个函数会返回 0，避免报错。

### 5.6 annualize_return()

把一段时间总收益换算成年化收益。

代码逻辑：

```python
(1 + total_return) ** (252 / periods) - 1
```

其中 252 是一年大约 252 个交易日。

## 6. 数据模块：src/data.py

核心类是：

```python
class DataClient:
```

它负责：

- 读取 Tushare token
- 设置代理
- 请求 Tushare
- 缓存数据
- 读取本地 CSV
- 统一字段格式

### 6.1 为什么要封装 DataClient

如果每个文件都直接调用 Tushare，代码会很乱。

封装后，其他模块只需要说：

```python
client.get_etf_daily(...)
```

不用关心 token、代理、缓存、异常处理这些细节。

### 6.2 cached_call()

这是缓存的核心。

逻辑：

```text
根据接口名和参数生成一个唯一文件名
如果本地已有缓存且 refresh=False，直接读 CSV
否则请求 Tushare，并把结果保存到 CSV
```

你可以把它理解成：

```python
path = self._cache_path(name, params)
if path.exists():
    return pd.read_csv(path)
df = tushare_api(...)
df.to_csv(path)
return df
```

### 6.3 get_etf_daily()

获取 ETF 日线。

优先级：

1. 读 `data/local_csv/` 本地 CSV。
2. 如果没有本地 CSV，就调用 Tushare `fund_daily`。
3. 如果失败，返回空表，主流程会跳过该 ETF。

### 6.4 get_index_daily()

获取指数日线，例如沪深300。

如果失败，不让整个程序崩溃，而是返回空表。后续市场状态会自动降级。

## 7. ETF 池模块：src/universe.py

这个文件很简单。

```python
def load_universe(config: dict) -> pd.DataFrame:
```

作用：

1. 从 `config.yaml` 读取 `etf_universe`。
2. 转成 DataFrame。
3. 检查必要字段是否存在。

必要字段包括：

```text
etf_code
etf_name
theme
```

如果缺字段，直接报错。

## 8. 日线特征：src/features_daily.py

这是量化初学者最值得认真读的文件之一。

### 8.1 add_daily_features()

输入：

```text
某只 ETF 的日线行情表
```

输出：

```text
加上均线、收益率、波动率、回撤、拥挤度、趋势状态的新表
```

核心计算：

```python
out["ma20"] = out["close"].rolling(20).mean()
out["ret_60"] = out["close"].pct_change(60)
out["vol_20"] = out["daily_ret"].rolling(20).std() * np.sqrt(252)
```

你可以逐行读它，因为它基本就是“用收盘价算各种指标”。

### 8.2 trend_pass

```python
out["trend_pass"] = (out["close"] > out["ma60"]) & (out["ma20"] > out["ma60"])
```

意思是：

```text
收盘价站上 60 日均线
并且 20 日均线高于 60 日均线
```

这是成长资产比较严格的趋势过滤。

### 8.3 amount_crowding

```python
out["amount_crowding"] = out["avg_amount_20"] / out["avg_amount_120"] - 1
```

意思是：

```text
最近 20 日成交额是否明显高于过去 120 日平均水平。
```

数值越高，说明交易越拥挤，策略会小幅扣分。

### 8.4 weekly_signal_dates() 和 biweekly_signal_dates()

`weekly_signal_dates()` 找每周最后一个交易日。

`biweekly_signal_dates()` 在周度信号中隔一个取一个，实现双周调仓。

## 9. 基本面与红利：src/features_fundamental.py

这个文件相对复杂，不建议第一遍逐行硬啃。先理解流程。

主函数：

```python
compute_fundamental_scores(config, as_of_dates)
```

它的目标是给每个调仓日、每只 ETF 算低频基本面特征：

- 股息率
- PB
- PE
- 估值分位
- 红利利差
- 基本面得分

### 9.1 月度低频计算

基本面不需要每天算，所以代码先把调仓日压缩到月度：

```python
monthly_dates = as_of.groupby(as_of.dt.to_period("M")).max().tolist()
```

意思是：

```text
每个月只取最后一个调仓日来拉基本面。
```

这样能减少 Tushare 调用次数。

### 9.2 _load_constituents()

尝试获取 ETF 对应的成分股。

优先级：

1. 如果有跟踪指数，用 `index_weight`。
2. 如果没有跟踪指数，用申万行业 `index_member`。
3. 如果都没有，记录问题，后面使用手工降级。

### 9.3 _weights()

决定成分股加权方式。

优先级：

1. 有指数权重就用指数权重。
2. 没有权重就用流通市值 `circ_mv`。
3. 都没有就等权。

### 9.4 _weighted_harmonic_pe()

PE 不能简单加权平均。

项目里用调和平均法估算组合 PE，这是金融里更合理的做法。

你可以先记住结论：

```text
组合 PE 用调和平均比普通平均更稳健。
```

### 9.5 _rolling_percentile()

计算某个指标在过去 36 个月中的历史分位。

例如 PB 分位：

```text
当前 PB 比过去 36 个月中多少月份更高？
```

如果分位很高，说明估值偏贵。

### 9.6 _add_dividend_spread()

计算红利利差：

```text
dividend_spread = 股息率 - 10 年国债收益率
```

这里用 Tushare `yc_cb` 获取国债收益率，并且按月低频缓存，避免限频。

### 9.7 merge_fundamental()

把低频基本面表合并到日线截面里。

你可以理解成：

```text
日线特征表 + 基本面特征表
```

合并后，策略打分时就能同时看到技术面和红利/估值信息。

## 10. 市场温度：src/market_features.py

主函数：

```python
compute_market_context(config, signal_dates, benchmark)
```

它主要计算融资风险。

流程：

1. 对每个调仓日，请求 Tushare `margin`。
2. 汇总融资融券余额。
3. 计算融资余额历史分位。
4. 判断指数是否跌破 MA20。
5. 如果融资余额高分位且指数跌破 MA20，给出风险扣分。

核心规则：

```python
high = out["margin_balance_percentile"] > 0.85
very_high = out["margin_balance_percentile"] > 0.95
```

解释：

```text
融资余额处于历史高位，说明杠杆资金比较拥挤。
如果这时指数转弱，风险会放大。
```

结果会写入：

```text
data/fundamental/market_context.csv
outputs/market_data_issues.csv
```

## 11. 策略决策：src/strategy.py

这是策略“大脑”。

你可以按这几个函数理解：

```text
classify_market()
_style_score()
_trend_pass_by_style()
_select_for_style()
build_weekly_ranking()
_adjust_allocations()
```

### 11.1 classify_market()

判断市场状态。

输入：

- 当前调仓日所有 ETF 的日线截面 `snapshot`
- 基准指数当日特征 `benchmark_row`
- 融资风险等市场信息 `market_context`

输出：

```python
{
    "market_state": "strong/neutral/weak/crisis",
    "market_score": ...,
    "index_trend_score": ...,
    "breadth_score": ...,
    ...
}
```

这个函数回答：

```text
现在市场整体更适合进攻还是防守？
```

### 11.2 _structure_score()

判断是否有结构性行情。

主要看：

- Top3 ETF 的 60 日收益
- ETF 池中 60 日正收益比例
- Top3 ETF 相对沪深300是否有超额

如果局部行业足够强，会给市场状态加分。

### 11.3 _style_score()

风格内打分函数。

核心逻辑：

```python
score += weight * safe_zscore(values)
```

意思是：

```text
每个因子先标准化，再乘以权重，最后加总。
```

这就是“因子加权打分”的核心。

### 11.4 _trend_pass_by_style()

不同风格使用不同趋势要求：

| 风格 | 趋势要求 |
| --- | --- |
| 成长 | 严格，要求通过 `trend_pass` |
| 稳定红利 | 较宽松，站上 MA60 或 MA120 即可 |
| 周期价值 | 要站上 MA60，且 MA20 > MA60，且 60 日收益为正 |

为什么要分开？

```text
成长股没有趋势时风险大；
红利资产可以稍微放宽；
周期资产必须确认趋势，否则容易抄底失败。
```

### 11.5 _select_for_style()

在某个风格池内部选 ETF。

默认每个风格选 Top 1。

它还有一个缓冲机制：

```text
如果当前持仓排名仍在前 2，
或者和第一名分数差距不大，
就不轻易换仓。
```

这样可以减少频繁换仓和手续费。

### 11.6 _adjust_allocations()

根据结构行情和融资风险修正仓位。

例如：

```text
结构行情强：适度增加成长/周期
融资风险高：降低成长/周期，提高现金
```

### 11.7 build_weekly_ranking()

这是策略决策的总入口。

它做的事最多：

1. 合并基本面。
2. 计算流动性过滤。
3. 计算趋势过滤。
4. 判断市场状态。
5. 计算风格目标仓位。
6. 分风格计算 `style_score`。
7. 选出目标 ETF。
8. 输出完整 ranking 表。

`weekly_ranking.csv` 里的大部分字段都来自这里。

## 12. 回测引擎：src/backtest.py

这是整个项目的核心执行器。

### 12.1 BacktestResult

```python
@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    weekly_ranking: pd.DataFrame
    ...
```

`@dataclass` 可以理解成“自动帮你写初始化函数的数据盒子”。

回测结束后，所有结果都装在 `BacktestResult` 里。

### 12.2 prepare_features()

把每只 ETF 的原始行情变成特征表。

输入：

```python
price_data = {
    "512000.SH": df1,
    "512800.SH": df2,
}
```

输出：

```text
所有 ETF 拼成的一张大表 panel
```

### 12.3 _execution_dates()

把信号日映射到执行日。

例如：

```text
周五收盘后算信号
下一个交易日执行
```

这样避免用当天收盘信号当天成交的隐含未来函数问题。

### 12.4 run_backtest()

这是回测主循环。

你可以把它读成伪代码：

```text
初始化现金和持仓
for 每个交易日:
    先计算当天账户总权益
    如果今天是执行日:
        找到对应信号日
        取信号日的 ETF 截面
        计算 ranking 和目标仓位
        卖出不再持有的 ETF
        买入或调仓到目标权重
        扣手续费
    记录当天净值
    记录当天持仓
返回所有结果
```

### 12.5 cash、shares、equity

回测里最重要的三个变量：

| 变量 | 含义 |
| --- | --- |
| `cash` | 当前现金 |
| `shares` | 当前持有每只 ETF 的份额 |
| `equity` | 总资产 = 现金 + 持仓市值 |

`shares` 是一个字典：

```python
{
    "510880.SH": 85561.27,
    "159819.SZ": 203290.98,
}
```

### 12.6 买卖逻辑

卖出：

```text
如果某只 ETF 不在新目标持仓里，就卖出。
```

买入或再平衡：

```text
目标金额 = 当前总资产 * 目标权重
差额 = 目标金额 - 当前持仓市值
如果差额足够大，就交易。
```

这里会考虑：

- 手续费 `commission`
- 滑点 `slippage`
- 最小交易金额 `min_trade_value`
- 再平衡容忍度 `rebalance_tolerance`

## 13. 报告输出：src/report.py

主函数：

```python
save_outputs(result, config)
```

它把 `BacktestResult` 写成各种文件。

主要输出：

| 文件 | 来源 |
| --- | --- |
| `equity_curve.csv` | `result.equity_curve` |
| `trades.csv` | `result.trades` |
| `positions.csv` | `result.positions` |
| `weekly_ranking.csv` | `result.weekly_ranking` |
| `performance_summary.csv` | `performance_summary()` |
| `holding_pnl.csv` | `_pnl_reports()` |
| `closed_trade_pnl.csv` | `_pnl_reports()` |
| `backtest_report.md` | `_markdown_report()` |
| `equity_curve.png` | matplotlib 绘图 |
| `drawdown.png` | matplotlib 绘图 |

### 13.1 performance_summary()

计算常见绩效指标：

- 总收益
- 年化收益
- 年化波动率
- 最大回撤
- 夏普比率
- 胜率
- 交易次数
- 换手率
- 空仓比例
- 基准收益

### 13.2 _pnl_reports()

生成：

- 当前持仓浮盈浮亏
- 已平仓交易盈亏

它会把买入和卖出配对，估算每笔平仓的盈亏和持仓天数。

## 14. 窗口分析：scripts/window_backtest_analysis.py

这个脚本不重新跑策略，而是读取已有回测结果：

```text
outputs/equity_curve.csv
outputs/trades.csv
```

然后按窗口统计表现：

- 按年度：2021、2022、2023...
- 滚动 24 个月：每 6 个月滚动一次
- 最近 24 个月

输出：

```text
outputs/window_backtest_summary.csv
outputs/window_backtest_summary_readable.csv
outputs/window_backtest_report.md
outputs/factor_explanations.csv
```

这个脚本适合用来回答：

```text
策略是不是只在某一段行情有效？
牛市、熊市、震荡市表现是否不同？
```

## 15. 权限检测：src/access_check.py 和 scripts/check_tushare_access.py

这部分用来检查 Tushare token 能访问哪些接口。

### 15.1 AccessResult

```python
@dataclass
class AccessResult:
```

它记录一个接口检查结果：

- 接口名称
- 是否成功
- 行数
- 错误信息
- 是否需要降级

### 15.2 _try_call()

安全调用某个接口。

如果成功，返回成功结果。

如果失败，不让程序崩溃，而是把错误记录下来。

### 15.3 summarize_access()

根据权限检查结果生成降级建议：

- 60 分钟不可用：关闭 intraday。
- 基本面不可用：关闭或降级基本面。
- ETF 日线不可用：提示使用本地 CSV。

## 16. 60 分钟模块：src/features_intraday.py

当前默认关闭，但预留了函数：

```python
intraday_buy_filter(df, max_premium=0.05)
```

它检查：

- 60 分钟收盘价是否高于 60 小时均线。
- 20 小时均线是否强于 60 小时均线，或正在上行。
- 最近几根 K 线是否连续走弱。
- 当前价格是否相对 20 小时均线过热。

如果 60 分钟数据为空，它返回：

```python
(True, "intraday_unavailable")
```

意思是：

```text
数据不可用时不阻断主回测。
```

## 17. 测试：tests/

测试文件帮助你确认改代码后有没有破坏主流程。

### 17.1 tests/test_config.py

检查 `config.yaml` 是否能正常读取，ETF 池是否存在。

### 17.2 tests/test_features.py

检查日线特征是否能正常计算，例如均线、收益率、技术分数。

### 17.3 tests/test_backtest.py

用合成数据跑一遍回测。

这很重要，因为它不依赖 Tushare，也能验证主流程是否能跑通。

运行测试：

```bash
python -m pytest -q
```

## 18. 建议你如何读这套代码

### 第一遍：只看主流程

按这个顺序读：

1. `scripts/run_backtest.py`
2. `src/backtest.py` 的 `run_backtest()`
3. `src/strategy.py` 的 `build_weekly_ranking()`
4. `src/report.py` 的 `save_outputs()`

目标：

```text
知道程序从哪里开始，到哪里结束。
```

### 第二遍：看因子怎么算

读：

1. `src/features_daily.py`
2. `src/features_fundamental.py`
3. `src/market_features.py`

目标：

```text
知道每个 CSV 里的因子字段是怎么算出来的。
```

### 第三遍：看交易怎么发生

重点读 `src/backtest.py` 里这几块：

- `cash`
- `shares`
- `target_values`
- `trade_rows`
- `pos_rows`

目标：

```text
理解为什么某天买、某天卖、买了多少。
```

### 第四遍：尝试改一个小参数

建议从 `config.yaml` 改，不要直接改 Python。

例如：

- 把 `rebalance_tolerance` 从 `0.02` 改成 `0.03`
- 把 `stable_value` 在弱市场的仓位从 `0.70` 改成 `0.65`
- 把 `growth_factors.ret_60` 从 `0.25` 改成 `0.20`

每次只改一个地方，然后：

```bash
python scripts/run_backtest.py
python scripts/window_backtest_analysis.py
```

观察：

- 总收益是否变化
- 最大回撤是否变化
- 换手率是否变化
- 某些年份是否变好但另一些年份变差

## 19. 初学者最容易踩的坑

### 19.1 只看总收益

总收益不是全部。你还要看：

- 最大回撤
- 年化波动
- 夏普
- 换手率
- 分年度表现
- 滚动窗口表现

### 19.2 根据回测结果反复调参数

这是数据挖掘偏差。

正确方式是：

```text
先固定一个假设
再用训练区间调参数
最后用测试区间验证
```

当前 v0.4 暂时不做参数寻优。

### 19.3 忽略交易成本

频繁换仓可能让收益被手续费吃掉。

所以 v0.4 用：

- 双周再平衡
- 持仓缓冲
- 最小交易金额
- 再平衡容忍度

### 19.4 把基本面当买入信号

本项目的基本面只做辅助。

不能因为便宜或股息率高就买入。

原因：

```text
便宜可以更便宜。
高股息也可能来自市场对风险的定价。
```

## 20. 你下一步可以怎么学

建议学习路线：

1. pandas 基础：DataFrame、Series、merge、groupby、rolling。
2. 技术指标基础：收益率、均线、波动率、最大回撤。
3. 回测基础：信号日、执行日、仓位、手续费、净值曲线。
4. 因子基础：截面排序、z-score、权重合成、因子方向。
5. 风险控制：市场状态、空仓、降仓、回撤控制。
6. 复盘方法：看 `weekly_ranking.csv` 解释每次换仓。

如果你想手把手继续学，下一份文档可以专门拆 `src/backtest.py`，逐段解释“现金、持仓、买卖、净值”是怎么计算出来的。
