# 回测陷阱百科（Backtest Pitfalls Encyclopedia）

> SKILL.md 指向的「完整陷阱百科」。三大类共 48 条陷阱，逐条给出：为什么坑（why）→ 代码里长啥样（code smell，Python 反例）→ 怎么检测（detect）→ 怎么修（fix，正确做法）。
>
> **严重度标记**：`【fatal】` 致命，回测结论直接作废 / 实盘必亏；`【high】` 高危，系统性高估收益；`【medium】` 中危，量级失真但方向不一定反。

---

## 总览速查表

| # | 陷阱 | 严重度 | 类别 |
|---|------|--------|------|
| 1.1 | `shift(-n)` 引入未来值 | fatal | ① 未来函数 |
| 1.2 | 同 bar 信号即成交（收盘价偷价） | fatal | ① |
| 1.3 | 全样本 `fit` 归一化/标准化 | fatal | ① |
| 1.4 | `rolling(center=True)` / 全样本聚合 | fatal | ① |
| 1.5 | Target leakage（特征混入标签信息） | fatal | ① |
| 1.6 | 随机切分时序 / CV 泄漏 | fatal | ① |
| 1.7 | 后向填充 `bfill` / `interpolate` | fatal | ① |
| 1.8 | resample 后未 shift（未闭合 bar） | high | ① |
| 1.9 | repaint 指标（ZigZag/分形/find_peaks） | fatal | ① |
| 1.10 | point-in-time 缺失（成分股/财报/复权） | fatal | ① |
| 1.11 | 正向偏移索引 `arr[i+1]` | fatal | ① |
| 1.12 | 指标 warm-up / 边界泄漏 | medium | ① |
| 1.13 | 止盈止损用未来 high/low 判定 | high | ① |
| 1.14 | 全样本统计设阈值/参数 | high | ① |
| 1.15 | 执行时点泄漏（VWAP/结算价不可及时得） | high | ① |
| 1.16 | merge/join 对齐 bug 整体偏移 | high | ① |
| 2.1 | 仅样本内优化，无 OOS/walk-forward | fatal | ② 过拟合 |
| 2.2 | 网格只报最优参数（cherry-pick max） | fatal | ② |
| 2.3 | 同一数据反复试错（p-hacking） | high | ② |
| 2.4 | 幸存者偏差（只用现存标的） | fatal | ② |
| 2.5 | 前视/全样本选股（universe 偏差） | fatal | ② |
| 2.6 | 自由参数过多（曲线拟合） | high | ② |
| 2.7 | 样本量不足（交易数太少/周期太短） | high | ② |
| 2.8 | 多重检验无校正（factor zoo） | high | ② |
| 2.9 | 止盈止损阈值过度调优 | high | ② |
| 2.10 | 收益统计误用（simple vs log） | medium | ② |
| 2.11 | 忽略市场状态（单一 regime） | medium | ② |
| 2.12 | 横截面排名/标准化全样本算 | high | ② |
| 3.1 | 零手续费 / 不建模交易成本 | fatal | ③ 成交真实性 |
| 3.2 | 不区分 maker/taker | high | ③ |
| 3.3 | 完全无滑点 | fatal | ③ |
| 3.4 | 收盘价/同 bar 信号价成交 | fatal | ③ |
| 3.5 | 用 bar 内极值 high/low 成交 | high | ③ |
| 3.6 | 假设无限流动性 | fatal | ③ |
| 3.7 | 忽略做空成本（借券费） | high | ③ |
| 3.8 | 忽略资金费率 funding | high | ③ |
| 3.9 | 忽略 tick size / lot size 取整 | medium | ③ |
| 3.10 | 零延迟 / 无排队 | high | ③ |
| 3.11 | 涨跌停/熔断/无量仍成交 | high | ③ |
| 3.12 | 忽略保证金与强平/爆仓 | fatal | ③ |
| 3.13 | 忽略分红/送配/拆股复权 | high | ③ |
| 3.14 | 现金/保证金无约束（负现金） | high | ③ |
| 3.15 | 止损用理想价精确成交（忽略跳空） | high | ③ |

---

# ① 未来函数 / 数据泄漏（Look-ahead & Data Leakage）

这一类的共同特征：**在 t 时刻的决策里，用到了 t 时刻还不可能知道的信息**。它们会让夏普凭空翻几倍，实盘永远复现不了。统一防御口径：**决策在 bar 收盘，执行在下一 bar；任何进入 signal/feature 的列只能用 `.shift(>=1)`。**

## 1.1 `shift` 方向写反 / 用 `shift(-n)` 引入未来值【fatal】

**why** —— 特征对齐时把未来的值移到当前行。`df['x'].shift(-1)` 直接把下一根 K 线的值放到本根上，模型/信号在 t 时刻看到了 t+1 的数据。这是最经典也最隐蔽的未来函数，夏普能凭空翻几倍，实盘永远复现不了。

**code smell**

```python
# 反例：负数 shift 把未来值搬到当前行
df['feat_next_close'] = df['close'].shift(-1)          # t 行拿到了 t+1 收盘价
df['mom'] = df['close'].pct_change(-5)                 # 用了未来 5 根
df['signal'] = (df['close'] < df['close'].shift(-1)).astype(int)  # 直接抄答案
returns = df['signal'] * df['close'].pct_change()      # 未来函数 + 同期成交，双重作弊
```

**detect** —— grep / AST 搜负数 shift：正则 `\.shift\(\s*-\d` 或 `shift\(\s*-`；再搜 `diff\(\s*-`、`pct_change\(\s*-`、`.shift(periods=-`。AST 层面找 `Call(attr='shift')` 且第一个参数（或 `periods` 关键字）为负 `Constant` 或 `UnaryOp(USub)`。**区分**：特征矩阵里 `shift(-n)` 几乎必错；只有在显式构造 label / 未来收益 `y` 时才合法，需结合变量名（`target` / `label` / `fwd_ret`）放行。

**fix**

```python
# 正确：特征只能用 shift(>=1) 引入历史；标签的 shift(-1) 严格隔离在 y 列
X = pd.DataFrame(index=df.index)
X['feat_close'] = df['close'].shift(1)         # 只用历史（t 及之前）
X['mom_5'] = df['close'].pct_change(5).shift(1)

# 标签独立构造，绝不进 X
y = df['close'].pct_change().shift(-1)          # 下一根收益，命名带 fwd 提示
y.name = 'fwd_ret_1'

# 训练时硬约束：y 相关列不得出现在特征里
assert 'fwd_ret_1' not in X.columns
```

---

## 1.2 用当根收盘价生成信号又用同根收盘价成交（同 bar 无延迟）【fatal】

**why** —— `signal = close > ma` 在 bar t 收盘后才能算出，但回测里却用 bar t 的 `close` 成交，等于「知道了收盘价再以收盘价买入」。实盘里你算出信号时这根 bar 已经结束，最快只能下一根开盘成交。该坑让趋势/反转策略回测收益虚高 30%–300%。

**code smell**

```python
# 反例：信号和成交共用同一根 close
df['ma'] = df['close'].rolling(20).mean()
df['signal'] = (df['close'] > df['ma']).astype(int)   # bar t 收盘才算得出
df['ret'] = df['signal'] * df['close'].pct_change()   # 却用 bar t→t 的收益结算（偷价）

# 事件驱动里同样：on_bar 中既算信号又用同价下单
def on_bar(bar):
    if bar.close > sma(bar.close):
        order(price=bar.close)                         # 同 bar 收盘价成交
```

**detect** —— 同一段代码里信号条件用了 `close[t]` / `df['close']` / `data.close[0]`，而下单/记账价格也取 `close[t]`（同索引）。grep `signal` 与 `entry_price` / `fill` / `execution` 是否共用同一行 close。自研事件驱动里搜 `on_bar` 中既 `compute_signal(bar.close)` 又 `order(price=bar.close)`。`backtesting.py` 里 `self.buy()` 默认用当前 bar close 成交，若信号也基于当前 close 即同 bar。`vectorbt` 里 entries 用 close 生成而 `from_signals` 不设 `price=开盘` / 不 shift。

**fix**

```python
# 正确：信号与成交至少错开一根 bar，决策在 t 收盘、执行在 t+1
df['ma'] = df['close'].rolling(20).mean()
df['signal'] = (df['close'] > df['ma']).astype(int)
position = df['signal'].shift(1)                       # 持仓滞后一根
df['ret'] = position * df['close'].pct_change()        # 用 t→t+1 收益结算

# 或显式用 t+1 开盘成交
fill_price = df['open'].shift(-1)                       # 下一根开盘（成交价口径）
# vectorbt: pf = vbt.Portfolio.from_signals(close, entries.shift(1), exits.shift(1))
```

---

## 1.3 归一化/标准化在全样本上 `fit`（`StandardScaler.fit` 用整段数据）【fatal】

**why** —— `scaler.fit(X)` 用了包含测试集/未来段的全部数据来估计 mean/std（或 min/max、分位数），测试期的统计量泄漏进训练。模型间接见到了未来分布，样本外性能虚高。同理 PCA / 分箱 / Yeo-Johnson 全样本 fit 都是泄漏。

**code smell**

```python
# 反例：在切分前对整段 X 做 fit_transform
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)                     # 用了未来段的 mean/std
X_train, X_test = X_scaled[:n], X_scaled[n:]           # 切分发生在泄漏之后

# 手写全样本标准化同样泄漏
df['z'] = (df['factor'] - df['factor'].mean()) / df['factor'].std()  # 整列均值含未来
```

**detect** —— grep `StandardScaler` / `MinMaxScaler` / `RobustScaler` / `QuantileTransformer` / `PowerTransformer` / `PCA` / `KBinsDiscretizer` 后，检查 `.fit(` 或 `.fit_transform(` 是否作用在切分 train/test 之前的整段 X 上。强信号：同一文件里 `fit_transform` 出现在 `train_test_split` 之前，或 fit 的对象不是 `X_train`。也搜手写全样本标准化 `(df - df.mean()) / df.std()`（无 rolling/expanding/groupby 时间分组）。

**fix**

```python
# 正确：scaler 只在训练集 fit，放进 Pipeline + TimeSeriesSplit，每折独立 fit
from sklearn.pipeline import Pipeline
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
pipe = Pipeline([('scaler', StandardScaler()), ('model', model)])
scores = cross_val_score(pipe, X, y, cv=TimeSeriesSplit(n_splits=5))

# 在线/滚动场景用 expanding/rolling 做 point-in-time 标准化
w = 252
df['z'] = (df['factor'] - df['factor'].rolling(w).mean()) / df['factor'].rolling(w).std()
```

---

## 1.4 rolling/expanding 的 `center=True` 或全样本聚合泄漏【fatal】

**why** —— `df.rolling(w, center=True).mean()` 把窗口中心对齐，当前点的均值用到了未来 `w/2` 根数据。同理对整列做 `df.mean()` / `df.std()` / `df.quantile()` / `df.rank()` 再当特征，等于用了全期（含未来）统计量。z-score、分位排名类因子最常踩。

**code smell**

```python
# 反例：center=True 偷看未来半个窗口
df['ma_c'] = df['close'].rolling(20, center=True).mean()   # 用了未来 10 根

# 反例：整列 rank / quantile 当时间序列特征（含未来）
df['rank'] = df['factor'].rank(pct=True)                    # 跨全期排名 = 偷看未来
df['hi_q'] = df['factor'] > df['factor'].quantile(0.9)      # 阈值含未来分布
```

**detect** —— grep `center=True`（rolling/ewm 里出现即未来函数）；搜整列聚合当特征：`\.mean\(\)` / `.std()` / `.max()` / `.min()` / `.quantile(` / `.rank(` 且结果直接参与信号而非 rolling/expanding 包裹。**横截面 rank 合法**（同一时刻跨标的），**时间维 rank 必须 expanding**。检查 `.expanding()` 是否被误写成全列聚合。

**fix**

```python
# 正确：时间序列窗口一律 center=False（pandas 默认），只用过去 w 根
df['ma'] = df['close'].rolling(20).mean()                  # center=False

# 需要全历史统计就用 expanding（只含截至当前的数据）
df['rank'] = df['factor'].expanding().apply(lambda s: s.rank(pct=True).iloc[-1])

# 横截面统计：按 date groupby 在组内做，不跨时间
df['cs_rank'] = df.groupby('date')['factor'].rank(pct=True)
```

---

## 1.5 Target leakage：特征里混进了与标签同期或未来的信息【fatal】

**why** —— 特征矩阵里出现了 t+1 之后才能知道的列，或与标签强相关的派生列（如用未来收益算出的波动、用全期 label 编码的类别）。模型直接「抄答案」，训练/验证都高，实盘归零。

**code smell**

```python
# 反例：用未来收益派生特征，又把它喂进 X
y = df['close'].pct_change().shift(-1)
df['fwd_vol'] = y.rolling(5).std()        # 基于未来收益的波动
X = df[['rsi', 'fwd_vol']]                # fwd_vol 直接泄漏标签信息

# 反例：全样本 target encoding（含 test）
df['cat_te'] = df.groupby('category')['target'].transform('mean')  # 偷看全期 label
```

**detect** —— 数据流审计：找标签 `y`/`target`/`fwd_ret` 的构造表达式，反查其用到的原始列是否也出现在 X 里且未滞后。检测特征-标签近乎完美相关：对每个特征与 `y` 算 corr，`abs>0.95` 强警告。grep `TargetEncoder` / `mean encoding` / `groupby(...).transform('mean')` 是否在全样本上算。检查是否有列名含 `future`/`next`/`fwd`/`ahead` 却进了 features 列表。

**fix**

```python
# 正确：提交前跑「特征-标签相关性体检」
leak = X.apply(lambda c: c.corr(y)).abs().sort_values(ascending=False)
suspicious = leak[leak > 0.95]
assert suspicious.empty, f"疑似 target leakage: {list(suspicious.index)}"

# Target encoding 用 out-of-fold（CV 内折外编码），不在 test 上算
from sklearn.model_selection import TimeSeriesSplit
# 每折只用训练折统计去编码验证折，避免标签泄漏
```

---

## 1.6 训练/调参时见过测试集（切分前预处理、随机 split、CV 泄漏）【fatal】

**why** —— (1) `train_test_split(shuffle=True 默认)` 切时间序列，测试集里混进了随机打散的早期样本、且未来样本进了训练；(2) 特征工程/缺失填充/重采样在切分之前对全量做；(3) `KFold` / 普通 CV 对时序数据导致用未来折训练、过去折验证。调参 over 整段数据更是把测试集当成了开发集。

**code smell**

```python
# 反例：时序却用默认 shuffle=True 随机切
X_tr, X_te, y_tr, y_te = train_test_split(X, y)        # 默认 shuffle=True，未来样本进训练

# 反例：时序用普通 KFold / GridSearchCV
from sklearn.model_selection import GridSearchCV
gs = GridSearchCV(model, grid, cv=5)                    # 普通 KFold = 用未来折训练
gs.fit(X, y)
```

**detect** —— grep `train_test_split` 是否缺 `shuffle=False`（时序必须 False）；搜 `KFold` / `cross_val_score` / `GridSearchCV` 用在时间序列且 cv 不是 `TimeSeriesSplit`。检查 fillna / interpolate / scaler / 特征构造是否出现在 split 之前。AST：数据预处理节点与 split 节点的拓扑顺序。

**fix**

```python
# 正确：时序按时间切（shuffle=False），CV 用 TimeSeriesSplit / Purged K-Fold
X_tr, X_te = X.iloc[:n], X.iloc[n:]                     # 按时间切，无 shuffle
tscv = TimeSeriesSplit(n_splits=5)                      # 或带 embargo 的 Purged K-Fold

# 所有 fit 类预处理放进 Pipeline，在每折内执行
pipe = Pipeline([('scaler', StandardScaler()), ('model', model)])
best = GridSearchCV(pipe, grid, cv=tscv).fit(X_tr, y_tr)  # 调参/最终评估用不同 hold-out
```

> López de Prado《Advances in Financial Machine Learning》的 Purged K-Fold + embargo 是金融时序 CV 的标准做法。

---

## 1.7 后向填充 / 时间插值把未来值灌进当前（`bfill` / `interpolate`）【fatal】

**why** —— `df.fillna(method='bfill')`、`backfill`、`df.interpolate()` 默认会用之后的数据回填/插值当前缺失点，等于把未来已知值搬到过去。停牌、缺数据的标的最容易中招，回测里这些点被未来价格补齐。

**code smell**

```python
# 反例：后向填充 / 双向插值
df = df.fillna(method='bfill')                          # 用未来值回填当前
df['close'] = df['close'].interpolate()                # 默认 linear，双向用到后值
df['x'] = df['x'].fillna(df['x'].mean())               # 全列均值含未来
```

**detect** —— grep `bfill`、`backfill`、`method=['"]bfill`、`method=['"]backfill`、`.fillna(0).bfill`、`fillna(.*method=.*back`；搜 `interpolate(`（默认 linear 双向）和 `interpolate(method=.*time`。`.fillna(df.mean())` 用全列均值也是泄漏。

**fix**

```python
# 正确：只允许前向填充，插值仅向前，缺失统计量取自训练集历史
df = df.fillna(method='ffill')                         # 用过去最后已知值
df['close'] = df['close'].interpolate(limit_direction='forward')

# 缺失统计量用训练集且只用历史
fill_val = X_train['x'].median()
df['x'] = df['x'].fillna(fill_val)
# 停牌/无数据时段标记不可交易，而非回填
df['tradable'] = df['volume'] > 0
```

---

## 1.8 resample 后未 shift，聚合 bar 用了未闭合区间的未来部分【high】

**why** —— 把 1m 重采样成 1h：`df.resample('1H').agg(...)` 给出的是该小时「闭合后」的 OHLC，但若把这根 1h bar 的 close/high/low 直接对齐到该小时「开始」时刻去做决策，就用了这一小时内尚未发生的数据。`label='left'` 配合 close 尤其危险。多周期对齐（日线信号驱动分钟级交易）最常翻车。

**code smell**

```python
# 反例：日线指标 merge 回分钟数据但方向/滞后错
daily = df.resample('1D').agg({'close': 'last'})
daily['ma'] = daily['close'].rolling(5).mean()         # 当日闭合后才算得出
# 直接 merge 回分钟，未 shift，导致当日盘中就用到当日收盘 MA
m = pd.merge_asof(minute_df, daily, on='datetime', direction='forward')  # forward = 偷看未来
```

**detect** —— grep `.resample(` 后检查是否对结果做了 `.shift(1)` 滞后再 merge/对齐回高频；搜 `label='left'` / `closed='left'` 与后续是否当成 bar 起点使用。检查多周期：日线指标 `merge_asof` 回分钟数据时方向是否 `backward`（应 backward，且日线值须为上一交易日）。`pd.merge_asof` 缺 `direction='backward'` 或用 `'forward'`/`'nearest'` 即泄漏。

**fix**

```python
# 正确：慢周期指标统一 shift(1) 后下沉，merge_asof 用 backward
daily['ma'] = daily['close'].rolling(5).mean().shift(1)   # 上一交易日才可用
m = pd.merge_asof(minute_df, daily, on='datetime',
                  direction='backward',                   # 只能看过去
                  allow_exact_matches=False)              # 同时刻通常应 False，避免用当根刚闭合值
```

---

## 1.9 repaint 指标 / 会回溯重画的信号（ZigZag、未来确认的分形/枢轴、重绘均线）【fatal】

**why** —— ZigZag、Williams Fractal、Pivot High/Low、半 repaint 的 supertrend、用未来 K 线确认拐点的形态识别等，信号点在事后会被重新定位（repaint）。回测里它们「总能抄在最高/最低点」，实盘当下根本不会触发或位置完全不同。

**code smell**

```python
# 反例：scipy.signal.find_peaks 对整段序列找极值 = 未来函数
from scipy.signal import find_peaks
peaks, _ = find_peaks(df['high'].values)               # 极值用到了峰值两侧（含未来）的数据
df.loc[df.index[peaks], 'sell_signal'] = 1             # 信号「正好」打在最高点

# argrelextrema 同理；自实现 zigzag/fractal/pivot 都会回溯重画
```

**detect** —— grep 指标名：`zigzag`、`ZigZag`、`fractal`、`pivot_high`/`pivot_low`、`peak`/`argrelextrema`、`find_peaks`、`supertrend` 自实现。检测形态识别函数是否输入了整段 array 一次性算极值/拐点（而非逐 bar 因果计算）。搜 talib 里需要居中/未来确认的形态。

**fix**

```python
# 正确：极值需「确认延迟」——其后 n 根都未被突破才视为成立，信号时间戳推后 n 根
def causal_swing_high(high, n=3):
    sig = pd.Series(0, index=high.index)
    for i in range(n, len(high) - n):
        window_left = high.iloc[i - n:i]
        if high.iloc[i] > window_left.max():
            # 必须等到右侧 n 根确认未突破，信号落在 i+n（确认时刻）
            if high.iloc[i] >= high.iloc[i:i + n + 1].max():
                sig.iloc[i + n] = 1                    # 时间戳推后 n 根
    return sig

# repaint 稳定性测试：把数据截断到 t、重算、看 t 处值是否变化，变了就是 repaint
def repaint_test(indicator_fn, series, t):
    full = indicator_fn(series).iloc[t]
    truncated = indicator_fn(series.iloc[:t + 1]).iloc[t]
    assert full == truncated, f"repaint! t={t}: full={full} truncated={truncated}"
```

---

## 1.10 point-in-time 缺失：用了当下才公布的成分股/财报/调整后价格【fatal】

**why** —— (1) 用「当前」指数成分股回测历史（survivorship + 前视：那时根本不在指数里）；(2) 财报/财务因子按报告期对齐而非「发布日」对齐，等于提前几十天用了未公布的财报；(3) 用后复权（adjusted close）且把未来的拆股/分红调整因子用在了过去——后复权价隐含了未来的调整。这类泄漏在选股/多因子策略里最致命且最难发现。

**code smell**

```python
# 反例：用「最新」成分股回测历史，且财报按报告期对齐
current_members = get_sp500_today()                    # 当下成分股 → 幸存者 + 前视
hist = price[price['symbol'].isin(current_members)]

financials.merge(price, on='date')                     # 用 report_period 当日期（提前用未公布财报）
df['eps'] = financials['eps']                          # 实际公告日在报告期后几十天
```

**detect** —— 审数据来源：成分股列表是否带生效区间（`effective_date` / 历史成分），还是一张「最新」表；财报字段是否有 `publish_date`/`announce_date` 并据此 lag，而非 `report_period` 直接对齐。grep `report_date`/`fiscal_period` 对齐却无 `announce_date`/`pit`/`publish`；grep `adj_close`/`adjusted`/后复权 是否被当训练特征。检查 `financials.merge(price, on='date')` 是否用财报期当日期。

**fix**

```python
# 正确：成分股按历史生效区间取，财报按公告日对齐并加发布滞后
def universe_at(date, membership):                     # membership 带 [start, end] 生效区间
    m = membership[(membership['start'] <= date) & (membership['end'] > date)]
    return set(m['symbol'])

# 财报按 announce_date 对齐，并加保守滞后（常用次日可用）
fin = financials.copy()
fin['available_at'] = fin['announce_date'] + pd.Timedelta(days=1)
df = pd.merge_asof(price.sort_values('date'), fin.sort_values('available_at'),
                   left_on='date', right_on='available_at', direction='backward')
# 价格用前复权（以回测起点为基准）或每个时点用「截至当时已知」的调整因子
# 无 PIT 数据就显式标注：该回测结果不可信
```

---

## 1.11 `.iloc`/`.loc`/数组索引正向偏移取到未来（`arr[i+1]`、`df.iloc[i:i+k]`）【fatal】

**why** —— 事件循环里 `for i in range(n): use(close[i+1])` 或 `future_window = df.iloc[i:i+horizon]` 直接读了未来索引；有人用「窗口内最大涨幅」当特征却把窗口取在 i 之后。numpy / 自研事件驱动最常见，因为没有 pandas 的对齐保护。

**code smell**

```python
# 反例：正向偏移读取未来
for i in range(len(close) - 1):
    if close[i + 1] > close[i]:                         # 读了下一根 = 未来函数
        signal[i] = 1
    fut = df.iloc[i:i + 20]['high'].max()              # 未来 20 根的最高价当特征
    feat[i] = fut / close[i]
```

**detect** —— AST/正则搜正向偏移索引：`\[\s*i\s*\+\s*\d`、`\[\s*t\s*\+`、`iloc\[\s*\w+\s*:\s*\w+\s*\+`、`\[idx\+\d:`、`close\[.*\+1\]`。检查循环变量 i 后面出现 `i+1`/`i+n` 的下标读取（写当然可以，读 = 未来）。自研引擎搜 bar 缓冲区是否能访问 `self.bars[i+1]` 或 `lookahead` 参数 `>0`。

**fix**

```python
# 正确：当前时刻 i 只允许访问 [..i+1) 切片（含 i，不含 i+1）
def only_past(series, i):
    """统一管控索引上界：返回截至 i（含）的视图，杜绝越界读未来。"""
    return series.iloc[:i + 1]

for i in range(len(close)):
    hist = only_past(df['close'], i)
    signal[i] = int(hist.iloc[-1] > hist.rolling(20).mean().iloc[-1])

# 未来窗口标签单独算、单独输出 y，严禁回灌特征
y = df['high'].rolling(20).max().shift(-20) / df['close'] - 1   # 命名+隔离
```

---

## 1.12 技术指标 warm-up 期未处理 / 整段计算导致边界泄漏【medium】

**why** —— MA/EMA/RSI 等在序列头部 warm-up 阶段值不稳定或为 NaN，直接交易这些点会失真；更严重的是某些库/手写指标对整段数组做归一化（如 `(x-min)/(max-min)` 用全段 min/max）再切片，边界处含未来。EMA 的 `adjust=True` 在 pandas 里也会随序列长度变化（轻微非因果于截断点）。

**code smell**

```python
# 反例：整段 min-max 归一化（边界含未来），且不丢 warm-up
df['norm'] = (df['close'] - df['close'].min()) / (df['close'].max() - df['close'].min())
df['ema'] = df['close'].ewm(span=20, adjust=True).mean()   # adjust=True 随长度变化
df['signal'] = (df['ema'] > df['close'])                   # 未丢前 20 根 warm-up
```

**detect** —— grep `ewm(.*adjust=True`（默认 True，做截断稳定性测试）、`(x - x.min()) / (x.max() - x.min())` 整段 min/max、talib 指标后未 dropna 直接进信号。检查指标输出是否做了 warm-up 截断（前 period 根丢弃）。做「截断重算稳定性测试」可一并发现。

**fix**

```python
# 正确：丢弃 warm-up，归一化改 rolling/expanding，EMA 用 adjust=False（严格因果）
w = 20
df['norm'] = (df['close'] - df['close'].rolling(w).min()) / \
             (df['close'].rolling(w).max() - df['close'].rolling(w).min())
df['ema'] = df['close'].ewm(span=w, adjust=False).mean()   # 纯递归，因果
df = df.iloc[w:]                                           # 丢弃前 max(period) 根 warm-up
```

---

## 1.13 止盈止损/出场用未来 bar 的 high/low 判定却以理想价成交【high】

**why** —— 回测里判断「这根 bar 触及了止损价」用了 bar 的 low/high（未来才知道的极值），却假设成交在恰好的止损/止盈价，且当同一根 bar 同时触及止损和止盈时默认「有利的那个先成交」。这既用了 bar 内未来信息，又给了乐观成交假设，胜率/盈亏比虚高。

**code smell**

```python
# 反例：同根判定 + 乐观成交 + 假设利好优先
for i in range(len(df)):
    if df['high'].iloc[i] >= tp:                        # 用 bar 内极值判定
        exit_price = tp                                # 假设恰好成交在止盈价
    elif df['low'].iloc[i] <= stop:
        exit_price = stop
    # 同根同时触及 tp 和 stop 时，先判 tp → 默认利好优先（乐观偏差）
```

**detect** —— 搜出场逻辑里 `bar.low <= stop` / `bar.high >= take_profit` 同根判定后 `fill_price` 直接取 stop/tp；检查同一根 bar 同时满足止损与止盈时的处理（是否假设利好优先）。grep `low <=` / `high >=` 与 `stop` / `tp` / `take_profit` 共现。vectorbt / backtesting.py 的 sl/tp 默认用 bar 内极值需确认成交价假设。

**fix**

```python
# 正确：同根同触按「止损先成交」（最坏假设），并加滑点惩罚
for i in range(len(df)):
    hit_stop = df['low'].iloc[i] <= stop
    hit_tp = df['high'].iloc[i] >= tp
    if hit_stop and hit_tp:
        exit_price = stop * (1 - slippage)             # 最坏假设：止损先成交
    elif hit_stop:
        exit_price = stop * (1 - slippage)
    elif hit_tp:
        exit_price = tp * (1 - slippage)
# 或下沉到更细周期/逐 tick 判定真实触发顺序
```

---

## 1.14 全局阈值/参数用了全样本统计来设定（动态阈值偷看全期分布）【high】

**why** —— 信号阈值取 `df['factor'].quantile(0.9)`、仓位上限用全期波动率、标准化阈值用 `mean±2std`——这些统计量来自包含未来的整段数据。等于用「上帝视角的分布」设定规则，样本外阈值会漂移，实盘表现塌方。

**code smell**

```python
# 反例：阈值/参数右侧是整列聚合（含未来）
hi = df['factor'].quantile(0.9)                         # 全期 90 分位
df['signal'] = df['factor'] > hi                       # 用上帝视角分布设规则
vol_cap = df['ret'].std() * 2                           # 全期波动率定仓位上限
```

**detect** —— grep 阈值/参数赋值右侧是否为整列聚合：`quantile(`、`.mean()`、`.std()`、`.median()`、`np.percentile(`，且作用对象是完整序列而非 rolling/expanding 或仅训练集。检查 `threshold = some_full_series_stat` 模式。**区分**：回测报告里事后算统计 OK；进入信号决策的阈值必须 PIT。

**fix**

```python
# 正确：阈值用 expanding/滚动历史统计实时更新，或训练集定标后冻结
df['hi'] = df['factor'].expanding(min_periods=252).quantile(0.9)   # 只用历史
df['signal'] = df['factor'] > df['hi']

# 或在训练集上定标，冻结用于样本外
hi_frozen = X_train['factor'].quantile(0.9)
df['signal_oos'] = df['factor'] > hi_frozen
# 自问：这个时点真能算出这个统计量吗？
```

---

## 1.15 用收盘价/VWAP 等当根聚合价做信号但实盘无法及时获得（执行时点泄漏）【high】

**why** —— 信号依赖当根 VWAP、收盘竞价价、当日结算价等只有 bar 结束后才确定的价，却假设在 bar 内/收盘瞬间就能以该价成交。日内策略用当日 VWAP 算信号又用当日均价成交是典型；close auction 价更是收盘后才出。轻则虚高，重则逻辑根本不可执行。

**code smell**

```python
# 反例：用当日 VWAP / typical_price 算信号并同期成交
df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()  # 当日累计 VWAP
df['typ'] = (df['high'] + df['low'] + df['close']) / 3                      # 需 close 才算得出
df['signal'] = df['close'] > df['vwap']                                     # 收盘后才确定
df['fill'] = df['vwap']                                                     # 却假设能以 VWAP 成交
```

**detect** —— grep `vwap`、`twap`、`settle`/`settlement`、`auction`、`typical_price=(h+l+c)/3` 是否在同根用于信号且成交也假设该价。检查 `(high+low+close)/3` 类「需要 close 才能算」的价被当作 bar 内可得。日内：日级 vwap 是否被分钟级决策即时引用。

**fix**

```python
# 正确：明确每个价的「可得时间」，聚合价只能用于下一可交易时点
df['vwap_prev'] = df['vwap'].shift(1)                  # 上一根已闭合 VWAP 才可用于决策
df['signal'] = df['close'].shift(1) > df['vwap_prev']  # 信号基于已闭合数据
df['fill'] = df['open']                                # 执行用下一根开盘
# 把「数据可得延迟」作为回测引擎的一等参数（data_available_lag）
```

---

## 1.16 merge/join/concat 后索引错位导致整体偏移泄漏（对齐 bug）【high】

**why** —— 不同频率/来源的数据 merge 时索引没对齐，或 concat 后 `reset_index` 导致行错位，signal 和 price 整体差了一行，可能恰好让信号「提前一根」看到价格 = 未来函数。reindex 后 ffill 方向错、join 后未排序也会引入。这类 bug 沉默且偶发，回测莫名其妙变好就要怀疑它。

**code smell**

```python
# 反例：不同索引 concat 直接拼接 + reset_index 破坏顺序
merged = pd.concat([signal_df, price_df], axis=1)      # 索引不一致 → NaN 错位
merged = merged.reset_index(drop=True)                 # 丢掉时间索引，行可能错位
merged['ret'] = merged['signal'] * merged['price'].pct_change()  # 相位可能差一根
```

**detect** —— 检查 merge/join 后是否 `sort_index` / `sort_values(by='datetime')`；grep `reset_index(` 后是否破坏时间顺序；`pd.concat([...], axis=1)` 不同索引对象直接拼接（NaN 错位）；`reindex(` 后 ffill/bfill 方向。做一致性断言：`assert (signal.index == price.index).all()` 和时间单调递增。

**fix**

```python
# 正确：merge 前后强制按时间排序并断言对齐，统一用 merge_asof(backward)
signal_df = signal_df.sort_index()
price_df = price_df.sort_index()
merged = pd.merge_asof(price_df, signal_df, left_index=True, right_index=True,
                       direction='backward')

# 回测入口守卫
assert merged.index.is_monotonic_increasing, "时间索引非单调递增"
assert (merged.index == price_df.index).all(), "signal/price 索引未对齐"
```

---

# ② 过拟合 / 数据窥探 / 幸存者偏差（Overfitting & Data Snooping）

这一类不"偷看未来某个值"，而是**把噪声当信号拟合进了参数**，或**只展示样本里活下来/表现好的那部分**。回测光鲜，样本外回归均值。统一防御口径：**参数从经济先验来、样本外验证、对"试了多少次"诚实。**

## 2.1 只在样本内优化，没有样本外 / walk-forward【fatal】

**why** —— 用全部历史调参，再用同一段历史报告夏普。参数是对这段数据的噪声量身定做的，样本外必然回归。没有 OOS 的回测约等于"先看答案再做题"。

**code smell**

```python
# 反例：在整段数据上网格搜索，报告也用同一段
best = max(params, key=lambda p: sharpe(backtest(data, p)))   # 全样本调参
print(sharpe(backtest(data, best)))                           # 同段报告 → 必然好看
```

**detect** —— 找参数寻优（`for p in grid` / `optuna` / `GridSearchCV` / `argmax sharpe`）后，报告指标用的数据段是否与寻优段重叠。grep 是否存在 `train/test` 时间切分、`walk_forward`、`TimeSeriesSplit`、`oos`/`out_of_sample` 字样。**缺失即 fatal**。

**fix**

```python
# 正确：anchored walk-forward，参数只在过去拟合，指标只来自未参与拟合的未来段
def walk_forward(data, grid, train_years=3, test_months=6):
    oos = []
    for split in rolling_splits(data, train_years, test_months):
        best = max(grid, key=lambda p: sharpe(backtest(split.train, p)))  # 仅训练段
        oos.append(backtest(split.test, best))                           # 仅测试段
    return concat(oos)                                                    # headline 只看这个
```

## 2.2 网格搜索只报最优参数（cherry-pick the max）【fatal】

**why** —— 扫了 500 组参数，只挑夏普最高那组当"策略"。最大值是噪声的极值统计量，期望就比真实 alpha 高一大截（多重比较）。没有对"试了多少组"做惩罚，最优参就是过拟合的代名词。

**code smell**

```python
results = [(p, sharpe(backtest(data, p))) for p in grid]     # 扫 500 组
best_p, best_s = max(results, key=lambda x: x[1])            # 只报最高
print(f"夏普 {best_s:.2f}")                                  # 无任何多重检验惩罚
```

**detect** —— grep `max(` / `idxmax` / `argmax` / `study.best_params` / `best_score_` 紧跟一次大范围参数扫描；检查是否计算了 Deflated Sharpe / PBO / Bonferroni 校正。参数曲面是否检查"高原 vs 尖峰"。

**fix**

```python
# 正确：用 Deflated Sharpe Ratio（计入试验次数 N），并选参数高原而非尖峰
from scipy.stats import norm
def deflated_sharpe(sr, n_trials, n_obs, skew=0, kurt=3):
    sr_std = ((1 - skew*sr + (kurt-1)/4*sr**2) / (n_obs-1))**0.5
    sr0 = sr_std * norm.ppf(1 - 1/n_trials)            # 多重检验下的期望最大夏普
    return norm.cdf((sr - sr0) / sr_std)               # >0.95 才算显著
# 选择参数邻域整体表现稳健的"高原"，对单点尖峰保持怀疑
```

## 2.3 同一份数据反复试错（p-hacking / 研究者自由度）【high】

**why** —— 在一份数据上换几十上百种规则、指标、阈值，直到回测变好。即使每次都做了 OOS，整个研究过程已经把测试集"磨"成了开发集。表现为大量被注释掉的备选规则和反复微调的 magic number。

**code smell**

```python
# if rsi < 30:        # 试过
# if rsi < 27:        # 又试
if rsi < 27.3 and vol > 0.0184 and hour != 3:   # 一堆精确到小数的魔法数 = 拟合痕迹
    enter()
```

**detect** —— git 历史里同一策略文件大量提交、奇异 magic number（`rsi<27.3`、`vol>0.0184`）、成片注释掉的备选条件。问作者"这个回测试了多少个版本"。Combinatorially Symmetric Cross-Validation (CSCV) 估 PBO（过拟合概率）。

**fix**

```python
# 正确：预注册假设 + 锁箱(lockbox)，限制研究自由度
# 1) 先写下经济假设与参数范围，再碰数据
# 2) 留出一段从不参与研发的 lockbox，只在定稿后跑一次
# 3) 用 CSCV 估 PBO，PBO>0.5 视为很可能过拟合
```

## 2.4 幸存者偏差：只用"现存"标的回测历史【fatal】

**why** —— 用今天还在的股票/币种回测过去，破产退市的输家（雷曼、LUNA、FTT）被悄悄剔除。回测里"买入持有"永远赢，因为死掉的样本根本不在数据里。系统性高估收益、低估尾部风险。

**code smell**

```python
symbols = get_current_sp500()           # 今天的成分股
hist = load_prices(symbols, '2010', '2024')   # 拿去回测 2010 → 幸存者偏差
# 加密货币：写死 BTC/ETH/前100，已退市/归零的山寨币全不见了
```

**detect** —— universe 是否来自"当前"快照（`get_current_*` / 写死 ticker 列表）。检查数据集是否含退市/已下架标的及其最后成交价。grep `delisted` / `is_active` / `survivor` 相关处理是否缺失。

**fix**

```python
# 正确：用 point-in-time universe，含退市标的的完整收益（归零计 -100%）
def universe_at(date, membership_with_dates):       # 带历史成分与生效区间
    return survivorship_free_members(date, membership_with_dates)
# 退市/归零标的保留到摘牌日并记最终收益；crypto 含已下架币并记最后价
```

## 2.5 前视式选股 / 全样本筛选 universe（selection bias）【fatal】

**why** —— "选全期市值前 50""选有完整历史数据的币""剔除 `dropna()` 后不足的标的"——这些筛选用到了未来才知道的信息（谁活到了最后、谁市值涨上来了）。本质是 1.10 的 universe 版，但极易被当成"数据清洗"而忽视。

**code smell**

```python
# 反例：用全样本统计选标的
top = df.groupby('symbol')['mktcap'].mean().nlargest(50).index   # 全期平均市值
panel = df[df['symbol'].isin(top)]                               # 偷看了未来谁大
panel = panel.dropna()                                          # 丢掉未上市/已退市样本
```

**detect** —— grep universe 构造处是否用 `mean()` / `nlargest` / `dropna()` 跨全期筛标的；是否要求标的"有完整历史"（隐含幸存）。检查选股发生在回测循环外（一次性、用全数据）还是每个 rebalance 用 trailing 数据。

**fix**

```python
# 正确：每个调仓日只用截至当日的 trailing 数据选 universe
def pick_universe(date, df, lookback='1Y', top=50):
    win = df[(df['date'] <= date) & (df['date'] > date - pd.Timedelta(lookback))]
    return win.groupby('symbol')['mktcap'].last().nlargest(top).index
# 绝不要求标的拥有超过当前 bar 的数据
```

## 2.6 自由参数过多 / 曲线拟合（curve fitting）【high】

**why** —— 同时优化 7+ 个参数、每条规则配一个魔法数，自由度远超数据所能支撑。模型有足够旋钮去拟合任何历史曲线，样本外立刻散架。参数越多、每参数对应的独立交易越少，越危险。

**code smell**

```python
# 反例：十几个自由参数一起优化
params = dict(ma_fast=8, ma_slow=34, rsi_buy=27, rsi_sell=71,
              atr_mult=2.3, vol_filter=0.018, hour_skip=3,
              tp=0.041, sl=0.017, trail=0.009, ...)   # 自由度爆炸
```

**detect** —— 数一个策略里被优化的参数个数、magic number 密度；估"自由参数数 vs 独立交易笔数"比（每参数应 >>10 笔）。检查 walk-forward 中各窗口最优参是否剧烈跳变甚至变号（不稳定 = 拟合噪声）。

**fix**

```python
# 正确：从经济先验固定/共享参数，砍自由度
# - 跨资产共用同一组参数（而非每个标的单独调）
# - 用整数/粗网格而非精确到小数的魔法数
# - 要求每个自由参数对应 >>10 笔独立交易
# - 丢弃在 walk-forward 中变号的旋钮
```

## 2.7 样本量不足：交易笔数太少 / 周期太短【high】

**why** —— 30 笔交易的夏普 3.0 和 3000 笔的夏普 1.0，后者可信得多。夏普的标准误随交易数下降而暴涨；只覆盖一两年（尤其单边行情）的回测，统计上几乎说明不了任何问题。报夏普却不报 t 值/置信区间是危险信号。

**code smell**

```python
# 反例：22 笔交易、夏普 2.8，当成"圣杯"
print(f"夏普 {sharpe:.1f}  交易 {n_trades} 笔  区间 2023-01~2023-09")  # 太短太少
# 无 t-stat、无置信区间、无 bootstrap
```

**detect** —— 检查回测交易笔数（round trips）与时间跨度；夏普是否附 t 值/置信区间。经验：t ≈ Sharpe × √years，要求 |t| > 2（多重检验后更高）。交易 < 30–50 笔的结论基本不可用。

**fix**

```python
# 正确：报夏普必带 t 值，并用 block bootstrap 给出分布
import numpy as np
def sharpe_tstat(daily_ret):
    sr = daily_ret.mean() / daily_ret.std() * np.sqrt(252)
    years = len(daily_ret) / 252
    t = sr * np.sqrt(years)                       # 近似 t 统计量
    return sr, t                                  # |t|<2 → 不显著，慎用
# block bootstrap（保留自相关）重采样收益，给夏普 95% 置信区间
```

## 2.8 多重检验无校正（factor zoo / 一堆因子挑显著的）【high】

**why** —— 测了 100 个因子，按裸 `p<0.05` 留下"显著"的 5 个——纯随机也会有约 5 个假阳性。不做 FDR/Bonferroni 校正、不做 Deflated Sharpe haircut，整个因子库就是数据窥探的产物（Harvey & Liu 的"…and the Cross-Section of Expected Returns"专门讲这个）。

**code smell**

```python
# 反例：批量测因子，按裸 p 值留显著的
keep = [f for f in factors if ttest(f).pvalue < 0.05]   # 100 个里"显著"的全留
```

**detect** —— grep `pvalue < 0.05` / `< 0.01` 用在批量因子/策略筛选；是否有 `fdr_bh` / `multipletests` / `bonferroni` / `deflated`。问"一共测了多少个因子/策略候选"，与最终保留数对比。

**fix**

```python
# 正确：Benjamini-Hochberg FDR 或 Bonferroni 校正 + 提高新因子显著门槛
from statsmodels.stats.multitest import multipletests
reject, p_adj, *_ = multipletests([t.pvalue for t in tests], alpha=0.05, method='fdr_bh')
# 经验：全新因子要求 |t| > 3.0（Harvey-Liu-Zhu），并披露候选总数
```

## 2.9 止盈止损 / 出场阈值被过度调优【high】

**why** —— tp/sl/trailing 这几个参数对回测曲线极敏感，最容易被反复微调到"恰好躲过每次大回撤"。它们往往是过拟合的重灾区：换一段数据，最优 sl 完全不同。

**code smell**

```python
for sl in np.arange(0.005, 0.05, 0.001):       # 把止损精调到千分位
    for tp in np.arange(0.01, 0.10, 0.001):
        record(sl, tp, backtest(...))
best_sl, best_tp = pick_max(record)            # 选最贴合历史的一组
```

**detect** —— tp/sl/trailing 是否进了细网格优化、精度是否异常（千分位）；walk-forward 下最优 sl/tp 是否稳定。检查出场参数数量占总自由参数比重。

**fix**

```python
# 正确：出场参数从波动率/ATR 等先验导出，而非自由优化
sl = 2.0 * atr            # 用 ATR 倍数（先验），不逐点调优
tp = 3.0 * atr            # 固定盈亏比，跨资产共享
# 若必须优化，纳入 walk-forward 并检验跨期稳定性
```

## 2.10 收益统计口径误用：算术/复利、simple/log、年化因子错配【medium】

**why** —— 用算术累加代替复利、把 simple return 当 log return 相加、年化因子用错（股票日频 √252、crypto 24/7 用 √365、小时频用 √(365×24)）——都会让夏普/年化收益系统性失真，且方向不固定。expert 风控视角下这是高频低级错误。

**code smell**

```python
# 反例：用算术和当累计收益；年化因子写死 252 用于 crypto
cum = df['ret'].sum()                          # 应该是 (1+ret).prod()-1
sharpe = df['ret'].mean()/df['ret'].std()*np.sqrt(252)   # crypto 24/7 不是 252
```

**detect** —— grep 累计收益用 `.sum()` 还是 `(1+r).prod()`；年化因子 `sqrt(252)` 是否与数据频率/市场匹配（A股/美股 252、crypto 365、小时频 ×24）；simple 与 log 是否混用（log 可相加、simple 不可）。

**fix**

```python
# 正确：明确口径，年化因子随频率/市场设定
log_ret = np.log1p(df['ret'])                  # log 收益可相加
cum = np.expm1(log_ret.sum())                  # 复利累计
PERIODS = {'D_stock': 252, 'D_crypto': 365, 'H_crypto': 365*24}
ann = np.sqrt(PERIODS['D_crypto'])
sharpe = df['ret'].mean()/df['ret'].std()*ann
```

## 2.11 只在单一市场状态（regime）验证【medium】

**why** —— 只在 2020–21 加密牛市、或一段低波股市里验证，相当于只考了一种天气。趋势策略在牛市无敌、震荡市被反复打脸。混合整段样本报一个夏普，会掩盖策略其实只在某种 regime 有效。

**code smell**

```python
backtest(data['2020-10':'2021-04'])            # 只测一段单边牛
print(sharpe)                                  # 整段混合，不分 regime
```

**detect** —— 回测区间是否只覆盖单一行情；是否按子区间/regime（牛熊、高低波）拆分报告。检查是否至少含一个完整周期 + 一段压力期（如 2022）。

**fix**

```python
# 正确：按 regime 拆分表现，覆盖完整周期 + 压力期
regimes = {'bull': ('2020-10','2021-04'), 'bear': ('2021-11','2022-12'),
           'chop': ('2023-01','2023-12')}
for name, (s, e) in regimes.items():
    print(name, sharpe(backtest(data[s:e])))   # 每种 regime 都要能看
```

## 2.12 横截面排名 / 标准化用了全样本或跨时间统计【high】

**why** —— 多因子选股里对 factor 做 rank/zscore 时，若跨整个面板（所有时间×所有标的）一起算，就用了未来时点的横截面分布。正确做法是**每个时间截面内**独立排名/标准化。这是 1.4/1.14 在横截面策略里的具体形态，极常见。

**code smell**

```python
# 反例：跨全面板 rank / zscore（含未来时点）
df['rank'] = df['factor'].rank(pct=True)                       # 没有按 date 分组
df['z'] = (df['factor'] - df['factor'].mean()) / df['factor'].std()
```

**detect** —— grep `.rank(` / zscore 是否 `groupby('date')` / `groupby(level='datetime')`；横截面操作是否限定在单一时间截面内。无分组的面板级排名/标准化即泄漏。

**fix**

```python
# 正确：在每个时间截面内做横截面 rank / 标准化
df['rank'] = df.groupby('date')['factor'].rank(pct=True)
df['z'] = df.groupby('date')['factor'].transform(lambda s: (s - s.mean()) / s.std())
# 中性化（行业/市值）同样按 date 截面回归取残差
```

---

# ③ 成交真实性 / 成本与执行（Execution Realism）

这一类的共同特征：**回测假设成交是免费、即时、无限、永远成功的**。实盘里每一笔都要付费、要排队、会被拒、可能成交在更差的价。换手越高的策略，这类坑越致命——它能把一条年化 80% 的曲线直接打成负的。

## 3.1 零手续费 / 完全不建模交易成本【fatal】

**why** —— 找不到任何 commission/fee 设置，或设为 0。日内/高频策略年换手可达几百上千倍，0.1% 的单边费叠加后能吃掉全部利润甚至转负。"忽略成本的高频策略"几乎都是这么虚高的。

**code smell**

```python
# 反例：完全不提手续费
pnl = (position.shift(1) * df['close'].pct_change()).sum()    # 净 = 毛，无成本
# backtrader/vectorbt 未设 commission
cerebro.broker.setcommission(commission=0.0)                 # 或干脆没这行
```

**detect** —— grep `commission` / `fee` / `cost` / `setcommission` / `fees=` 是否存在且非 0；估算策略换手率，用"成本 = 换手 × 费率"粗算被忽略的量级。无任何成本项即 fatal。

**fix**

```python
# 正确：按交易所真实分层费率建模，并做成本敏感性
FEE = {'binance_spot_taker': 0.001, 'binance_perp_taker': 0.0004}
turn = position.diff().abs()                                  # 每期换手
cost = turn * FEE['binance_perp_taker']
net = position.shift(1) * df['close'].pct_change() - cost
# 关键：把费率 ×2 再跑一遍，若策略由正转负 → 成本敏感，不可信
```

## 3.2 不区分 maker / taker（成本结构错配）【high】

**why** —— 挂单(maker)和吃单(taker)费率差好几倍（有的交易所 maker 还返佣）。做市/被动策略若全按 taker 算会低估收益；激进/扫单策略若全按 maker 算会严重高估。用单一费率掩盖了真实成交方式。

**code smell**

```python
fee = 0.001                                   # 一刀切，不分挂/吃单
cost = turnover * fee                          # 被动做市策略被高估成本、激进策略被低估
```

**detect** —— 检查成本模型是否区分订单类型；策略下的是限价(maker)还是市价/穿价(taker)单，与所用费率是否匹配。做市策略却用 taker 费、扫单策略却用 maker 费都是错配。

**fix**

```python
# 正确：按订单类型分别计费，并对 maker 成交概率打折
MAKER, TAKER = -0.00005, 0.0004               # 部分所 maker 返佣为负
def fee_of(order):
    return MAKER if order.is_passive else TAKER
# 被动挂单还要乘以"成交概率"，未成交不产生收益（见 3.10）
```

## 3.3 完全无滑点（成交在理论价）【fatal】

**why** —— 没有滑点模型，成交价直接取 close/signal price。实盘有买卖价差，市价单还有冲击成本。净值曲线异常平滑、几乎无毛刺，往往就是零滑点的特征。换手高的策略尤其致命。

**code smell**

```python
fill_price = df['close']                       # 信号价 = 成交价，无点差无冲击
# 无 set_slippage / slippage 参数
```

**detect** —— grep `slippage` / `set_slippage` / `spread` / `impact` 是否存在；成交价是否等于信号/收盘价。净值曲线过于平滑、夏普高得离谱也是间接信号。

**fix**

```python
# 正确：至少半个~一个 spread + 与下单量挂钩的冲击成本（平方根法则）
def fill_with_slippage(side, mid, spread, qty, adv, k=0.1):
    half_spread = spread / 2
    impact = k * np.sqrt(qty / adv)            # 冲击 ∝ √(参与率)
    return mid + side * (half_spread + impact) * mid   # side=+1 买/-1 卖
```

## 3.4 用当根收盘价 / 信号价直接成交（执行侧偷价）【fatal】

**why** —— 与 1.2 同源，但从执行真实性角度看：即便信号已 shift，若仍假设"以触发信号那一刻的精确价"成交，也忽略了从决策到下单到撮合的全过程。最常见是"收盘价信号→收盘价成交"。

**code smell**

```python
if cross_up:                                   # 收盘后才确认
    enter_price = bar.close                     # 却假设能买在这个收盘价
```

**detect** —— 成交价是否取自触发信号的同一价位（close/触发价）；是否存在"决策→执行"的时间/价格间隔。市价单是否按下一可成交价而非信号价。

**fix**

```python
# 正确：决策在 t 收盘，成交按 t+1 开盘（或 t+1 VWAP）并叠加滑点
exec_price = df['open'].shift(-1) * (1 + side * slippage)   # 下一根开盘 + 滑点
```

## 3.5 用 bar 内极值 high/low 当成交价【high】

**why** —— 限价单回测里假设"价格触及 limit 即成交在 limit"，或止盈用 bar 的 high、止损用 bar 的 low——都用了 bar 内事后才知道的极值，且假设你恰好成交在最优点。同根 bar 同时触及止盈止损还默认有利方向先成交。

**code smell**

```python
if bar.low <= limit_buy:                        # 用 bar 内最低判定
    fill = limit_buy                            # 假设成交在理想 limit 价
```

**detect** —— 成交判定是否用 `bar.high/low`；限价成交是否假设"触及即全额成交在 limit"。同 bar 双触的处理顺序（见 1.13）。

**fix**

```python
# 正确：要求价格"穿过"而非仅"触及"，同 bar 双触按不利方向优先
hit = bar.low < limit_buy                       # 严格穿过
fill = limit_buy if hit else None               # 仅触及不保证成交
# 需要精确性就下沉到 tick 还原 bar 内真实路径
```

## 3.6 假设无限流动性（下单量远超盘口仍单价全成）【fatal】

**why** —— 回测里下 1000 万的单，假设全部成交在当时的 mid，无视盘口深度和 ADV。实盘里大单会扫穿订单簿、产生巨大冲击成本，或根本吃不到量。策略资金一放大，回测收益与实盘的差距呈非线性爆炸。

**code smell**

```python
qty = capital / price                           # 想买多少买多少
fill = price                                    # 不管盘口/成交量，全额单价成交
# 无 volume_limit / participation_rate 约束
```

**detect** —— grep `volume_limit` / `max_volume` / `participation` / `adv` 约束是否存在；下单量是否与 bar volume / ADV 比较。检查策略容量分析（capital 放大后夏普是否衰减）。

**fix**

```python
# 正确：参与率上限 + 超量拆单 + 画容量曲线
MAX_PART = 0.05                                  # 单 bar 至多吃该 bar 成交量的 5%
fill_qty = min(target_qty, bar.volume * MAX_PART)
# 不同 capital 规模重跑，画 capital→Sharpe 衰减曲线确定策略容量
```

## 3.7 忽略做空成本 / 借券费 / 不可借【high】

**why** —— 空头策略假设能免费、无限、随时做空。实盘要付借券费(borrow fee)，热门空头标的借券费极高甚至无券可借（hard-to-borrow）。回测里"完美做空"的 alpha 实盘可能全被借券费吃掉。

**code smell**

```python
short_pnl = -position * df['close'].pct_change()   # 空头收益，零持有成本
# 无 borrow_fee / short_rate，假设任意标的随时可空
```

**detect** —— 有空头仓位却无 `borrow` / `short_fee` / `short_rate` / `htb` 字段；是否校验标的可借性。grep 空头记账是否扣持有成本。

**fix**

```python
# 正确：空头计提日借券费，过滤不可借标的
borrow_daily = annual_borrow_rate / 252
short_cost = position.clip(upper=0).abs() * borrow_daily   # 仅空头部分计费
net = gross_pnl - short_cost
# 不可借/高费标的从空头 universe 剔除
```

## 3.8 忽略资金费率（永续合约 funding rate）【high】

**why** —— 永续合约多空双方按 funding rate 周期性互付。趋势/持仓型策略长期持有永续，funding 累计可观（年化常达 ±10%~±50%）。回测不计 funding，多头在正费率市场会被持续抽血，收益虚高。

**code smell**

```python
perp_pnl = position * df['close'].pct_change()   # 永续持仓，无 funding 结算
# 无 funding_rate / funding_interval（如每 8h）
```

**detect** —— 标的为永续(perp/swap)却无 `funding` / `funding_rate` 字段；是否在结算时点（如每 8 小时）按 `名义 × funding × 方向` 入账。

**fix**

```python
# 正确：每个结算点按持仓方向结算 funding
# 多头付正 funding、收负 funding；空头相反
funding_pnl = -position * notional * funding_rate          # 在每个 funding_time 累加
net = price_pnl + funding_pnl - fees
```

## 3.9 忽略最小变动价位 / 最小下单单位（tick size / lot size 取整）【medium】

**why** —— 回测用连续价格和连续仓位，实盘价格按 tick、数量按 lot/张取整。小资金、低价标的、合约张数策略影响明显：理论仓位 0.37 张实盘只能下 0 或 1 张，理论成交价 100.013 实盘只能 100.01。累积起来口径失真。

**code smell**

```python
qty = capital / price                           # 0.37 张这种小数仓位
fill = signal_price                             # 非 tick 对齐的精确价
```

**detect** —— 是否对数量做 `round`/`floor` 到 lot、对价格对齐到 tick；grep `tick_size` / `lot_size` / `min_qty` / `step_size`。合约策略尤其检查张数取整。

**fix**

```python
# 正确：价格对齐 tick，数量向下取整到 lot
import math
def round_price(p, tick): return round(p / tick) * tick
def round_qty(q, lot):    return math.floor(q / lot) * lot
qty = round_qty(capital / price, lot_size)      # 实际可下的整数量
```

## 3.10 零延迟 + 限价单"触及即成"（无撮合延迟 / 无排队）【high】

**why** —— 回测假设信号产生即刻成交、限价单价格触及即 100% 成交。实盘有网络/计算延迟（高频以毫秒~微秒计），被动限价单要排队，价格"触及"不代表轮到你成交。高频/做市策略不建模延迟与队列，回测全是幻觉。

**code smell**

```python
on_signal()                                     # 信号即下单即成交，无延迟
if price_touched(limit):                         # 触及即认为成交
    fill(limit, full_qty)                        # 100% 成交，无排队概率
```

**detect** —— grep `latency` / `delay` / `queue` / `fill_prob` 是否建模；信号到成交是否有时间间隔。高频策略是否考虑订单簿排队位置。被动限价是否假设全额成交。

**fix**

```python
# 正确：注入延迟 + 限价排队/成交概率模型
SIGNAL_TO_FILL = pd.Timedelta('50ms')           # 高频按真实 RTT
exec_time = signal_time + SIGNAL_TO_FILL
# 被动限价：要求价格穿过且按队列位置给成交概率，未成交不计收益
filled = (low < limit) and (random_queue_fill_prob() > threshold)
```

## 3.11 在涨跌停 / 熔断 / 无量时仍假设成交【high】

**why** —— A股一字涨停（open=high=low）你根本买不到，但回测照样成交；熔断、停牌(volume=0)期间假设流动性正常。这些极端时刻往往正是策略想进出的时候，能否成交直接决定真实回撤。

**code smell**

```python
fill(bar.close)                                  # 不检查涨跌停/停牌/无量
# 无 limit_up / limit_down / halt / volume==0 过滤
```

**detect** —— grep `limit_up` / `limit_down` / `halt` / `suspend` / `volume == 0` 过滤是否存在；是否在 `open==high==low`（一字板）上成交。停牌期(volume=0)是否仍记成交。

**fix**

```python
# 正确：封板/停牌/无量不成交
one_word_board = (bar.open == bar.high == bar.low)            # 一字板
tradable = (bar.volume > 0) and (not one_word_board) and (not bar.halted)
if not tradable:
    skip_order()                                # 极端行情下的"成交不了"才是真回撤
```

## 3.12 用杠杆/合约却忽略保证金与强平（爆仓）【fatal】

**why** —— 加了杠杆却不建模维持保证金和强制平仓。回测里权益可以深度为负然后"扛回来"，实盘早就被交易所强平清零了。一次爆仓就是本金归零、游戏结束，回测却当成一次普通回撤继续运行。

**code smell**

```python
equity = init + (leverage * position * ret).cumsum()   # 权益可为负仍持仓
# 无 maintenance_margin / liquidation 检查
```

**detect** —— 用了 `leverage` / 合约 / 永续却无 `margin` / `maintenance_margin` / `liquidation` / `mmr` 逻辑；权益序列是否出现过负值后又恢复（典型未建模爆仓）。

**fix**

```python
# 正确：每 bar mark-to-market，触及维持保证金即强平清零并统计爆仓
for bar in bars:
    equity += leverage * position * bar.ret * notional
    margin_ratio = equity / (abs(position) * notional)
    if margin_ratio < maintenance_margin_rate:   # 触发强平
        equity = 0; position = 0; liquidations += 1
        break                                    # 本金归零，一次即判失败
# 报告必须含"爆仓次数"，>0 通常意味着该参数下策略不可用
```

## 3.13 忽略分红 / 送配 / 拆股的价格复权【high】

**why** —— 跨除权除息日若用未复权价，会凭空出现"暴跌/暴涨"假信号；若用后复权(adjusted)价当特征又隐含了未来调整因子（见 1.10）。股票/ETF 长持策略不处理分红，总收益会系统性偏低（少了股息）。

**code smell**

```python
ret = raw_close.pct_change()                     # 未复权，除权日假跳空
# 或用后复权价当特征（隐含未来调整因子）
```

**detect** —— 价格是否处理除权除息；用的是未复权、前复权还是后复权，与用途是否匹配（特征用前复权/PIT，总收益要含股息）。grep `adjust` / `dividend` / `split` 处理。

**fix**

```python
# 正确：信号用前复权（以回测起点为基准，PIT），总收益单独加股息现金流
signal_price = forward_adjusted_close            # 前复权，不含未来信息
total_return = price_return + dividend / price    # 股息按除息日现金入账
# 拆股按 split ratio 调整持仓数量
```

## 3.14 现金 / 购买力无约束（隐性无限杠杆、负现金）【high】

**why** —— 下单前不校验现金/购买力，回测里现金可以是负数仍继续买入 = 隐性无限杠杆。无杠杆策略却跑出了加杠杆的收益，自己都没察觉。

**code smell**

```python
for sig in signals:
    buy(sig, size=target)                        # 不查现金，账户可买到负现金
```

**detect** —— 下单前是否校验 `cash` / `buying_power` >= 成交额；现金序列是否出现负值；无杠杆声明却隐含 >1 的总仓位。grep `buying_power` / `available_cash` 校验。

**fix**

```python
# 正确：下单前校验购买力，无杠杆策略硬约束总仓位 ≤ 权益
def can_afford(cash, price, qty, fee):
    return cash >= price * qty * (1 + fee)
if can_afford(cash, price, qty, FEE):
    buy(qty); cash -= price * qty * (1 + FEE)
# 融资买入须计融资利息；约束 sum(|position|*price) <= equity * max_leverage
```

## 3.15 止损用理想价精确成交，忽略跳空 / 滑点【high】

**why** —— 假设止损单总能恰好成交在止损价。实盘遇到跳空（隔夜利空、闪崩）会以远低于止损价的价格成交，止损形同虚设。回测里"每次都精确止损在 -2%"，实盘可能 -2% 的止损成交在 -8%。

**code smell**

```python
if price <= stop:
    exit_price = stop                            # 假设恰好成交在止损价
# 隔夜跳空开盘 -8%，回测仍记 -2% 止损
```

**detect** —— 止损成交价是否硬等于止损价；是否考虑 `open` 跳空越过止损（`open < stop` 时应按 open 成交）。grep 出场价是否取 `min(stop, next_open)` 类保守口径。

**fix**

```python
# 正确：跳空时按更差的开盘价成交，再叠加滑点
if bar.open <= stop:                             # 跳空越过止损
    exit_price = bar.open * (1 - slippage)       # 按实际开盘成交，不是理想止损价
elif bar.low <= stop:
    exit_price = stop * (1 - slippage)
```

---

## 怎么用这份清单

1. 按 `SKILL.md` 的**审查协议**定位代码区，对照三大类逐条 grep + 读上下文确认。
2. 每条都要**区分真坑与合法用法**——命中模式只是嫌疑，定位到 `文件:行` 读懂语义再定罪。
3. 按严重度汇总进**回测体检报告**，致命/高危优先。
4. **致命项清零前，不建议投入实盘资金。**

> 本文件随实战补充。发现新坑、误报或框架特定模式，欢迎提 PR（见仓库 README 的贡献指南）。
>
> 免责：本清单是**工程审查**参考，不构成投资建议，不预测收益、不保证通过审查的策略能盈利。一切交易决策与资金风险由使用者自行承担。
