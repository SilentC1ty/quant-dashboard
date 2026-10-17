from __future__ import annotations

import json
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .models import StrategyData

TRADING_DAYS = 252


@dataclass(slots=True, eq=False)
class BenchmarkData:
    """A local buy-and-hold benchmark built from quant research-price caches."""

    key: str
    display_name: str
    weights: dict[str, float]
    equity: pd.Series
    source_project: Path
    source_strategy_key: str = ""
    method: str = "adjusted_fractional_buy_hold"

    @property
    def composition(self) -> str:
        return " + ".join(f"{symbol} {weight:.0%}" for symbol, weight in self.weights.items())


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _research_cache_path(strategy: StrategyData, symbol: str) -> Path | None:
    if strategy.project_root is None:
        return None
    asset_type = str(strategy.universe.get("asset_type") or "etf")
    adjust = str(strategy.universe.get("adjust") or "none")
    return strategy.project_root / "data" / "cache" / f"{asset_type}_{symbol}_{adjust}.csv"


def _read_price_cache(path: Path, symbol: str) -> pd.Series:
    if not path.is_file():
        return pd.Series(dtype=float, name=symbol)
    try:
        raw = pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"价格缓存解析失败：{path.name}") from exc
    if "date" not in raw.columns or "close" not in raw.columns:
        return pd.Series(dtype=float, name=symbol)

    frame = raw[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame.isna().any().any() or (frame["close"] <= 0).any() or frame["close"].isin([math.inf, -math.inf]).any():
        raise ValueError(f"价格缓存含无效值：{path.name}")
    if frame.duplicated("date").any():
        raise ValueError(f"价格缓存日期重复：{path.name}")
    frame = frame.sort_values("date")
    if frame.empty:
        return pd.Series(dtype=float, name=symbol)

    series = frame.set_index("date")["close"].astype(float)
    series.name = symbol
    return series


def _strategy_date_range(strategy: StrategyData) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    if strategy.nav.empty or "date" not in strategy.nav.columns:
        return None, None
    dates = pd.to_datetime(strategy.nav["date"], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return pd.Timestamp(dates.min()), pd.Timestamp(dates.max())


def _build_buy_and_hold(
    prices: pd.DataFrame,
    weights: dict[str, float],
    commission: float,
    slippage: float,
    name: str,
) -> pd.Series:
    if not weights:
        raise ValueError("benchmark weights must not be empty")
    if any(weight < 0 for weight in weights.values()):
        raise ValueError("benchmark weights must be non-negative")

    invested_weight = float(sum(weights.values()))
    if invested_weight <= 0 or invested_weight > 1.0 + 1e-12:
        raise ValueError("benchmark weights must sum to a value in (0, 1]")

    selected = prices[list(weights)].dropna(how="any").astype(float)
    if selected.empty:
        raise ValueError("benchmark has no common price history")

    normalized = selected.div(selected.iloc[0])
    cash_weight = 1.0 - invested_weight
    gross_equity = pd.Series(cash_weight, index=selected.index, dtype=float)
    for symbol, weight in weights.items():
        gross_equity = gross_equity + normalized[symbol] * float(weight)

    one_way_cost = commission + slippage
    scale = 1.0 / (1.0 + one_way_cost * invested_weight)
    invested_component = gross_equity - cash_weight
    equity = cash_weight + invested_component * scale
    equity.name = name
    return equity.astype(float)


def _benchmark_definitions(strategy: StrategyData) -> list[tuple[str, str, dict[str, float]]]:
    raw_cfg = strategy.settings.get("benchmark", {})
    cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    definitions: list[tuple[str, str, dict[str, float]]] = []

    raw_balanced = cfg.get("balanced_weights", {})
    if isinstance(raw_balanced, dict) and raw_balanced:
        weights = {str(symbol): _float(weight) for symbol, weight in raw_balanced.items()}
        if weights:
            if len(weights) == 2 and sorted(round(value, 6) for value in weights.values()) == [0.4, 0.6]:
                label = "60/40 股债 Buy & Hold"
            else:
                label = "固定权重 Buy & Hold"
            key = "balanced:" + json.dumps(weights, sort_keys=True, ensure_ascii=True)
            definitions.append((key, label, weights))

    symbol = str(cfg.get("csi300_symbol") or "").strip()
    if symbol:
        name = strategy.names.get(symbol, symbol)
        definitions.append((f"single:{symbol}", f"{name} Buy & Hold", {symbol: 1.0}))

    return definitions


def load_benchmarks(strategy: StrategyData) -> tuple[list[BenchmarkData], list[str]]:
    """Load configured benchmarks from a strategy's local quant research cache."""

    definitions = _benchmark_definitions(strategy)
    if strategy.project_root is None:
        return [], [f"{strategy.display_name}: 未找到项目根目录，无法读取 benchmark 价格缓存。"]

    raw_cost = strategy.settings.get("cost", {})
    cost_cfg = raw_cost if isinstance(raw_cost, dict) else {}
    commission = _float(cost_cfg.get("commission"), 0.0)
    slippage = _float(cost_cfg.get("slippage"), 0.0)
    start, end = _strategy_date_range(strategy)

    loaded: list[BenchmarkData] = []
    warnings: list[str] = []
    for key, label, weights in definitions:
        series: list[pd.Series] = []
        missing: list[str] = []
        for symbol in weights:
            cache_path = _research_cache_path(strategy, symbol)
            if cache_path is None:
                missing.append(symbol)
                continue
            try:
                price = _read_price_cache(cache_path, symbol)
            except ValueError as exc:
                missing.append(str(exc))
                continue
            if price.empty:
                missing.append(f"{symbol} ({cache_path})")
            else:
                series.append(price)

        if missing:
            warnings.append(f"{strategy.display_name}: {label} 缺少本地价格缓存：{', '.join(missing)}")
            continue

        prices = pd.concat(series, axis=1).sort_index()
        if start is not None:
            prices = prices.loc[start:]
        if end is not None:
            prices = prices.loc[:end]
        prices = prices.dropna(how="all")
        if prices.empty:
            warnings.append(f"{strategy.display_name}: {label} 在模拟盘日期范围内没有可用价格。")
            continue

        expected = pd.DatetimeIndex(pd.to_datetime(strategy.nav.date))
        if prices.reindex(expected).isna().any().any():
            warnings.append(f"{strategy.display_name}: {label} 缺少策略区间的价格，暂停基准比较。")
            continue
        prices = prices.reindex(expected)

        try:
            equity = _build_buy_and_hold(prices, weights, commission, slippage, label)
        except ValueError as exc:
            warnings.append(f"{strategy.display_name}: {label} 无法构造：{exc}")
            continue

        loaded.append(
            BenchmarkData(
                key=key + ":" + hashlib.sha256((strategy.key + str(strategy.project_root) + str((start, end, commission, slippage)) + prices.to_csv()).encode()).hexdigest()[:16],
                display_name=label + f" · {strategy.display_name}",
                weights=weights,
                equity=equity,
                source_project=strategy.project_root,
                source_strategy_key=strategy.key,
            )
        )

    return loaded, warnings


def initial_fills_benchmark(strategy: StrategyData) -> BenchmarkData:
    """Same actual initial fills/costs/cash, then no further trading or reinvesting."""
    from .metrics import clean_nav
    nav = clean_nav(strategy)
    if nav.empty:
        raise ValueError("没有 NAV 日期")
    dates = pd.DatetimeIndex(nav.date)
    initial = float(strategy.state["initial_cash"])
    origin = strategy.state.get("origin", {})
    opening = origin.get("opening_holdings", {})
    if opening:
        quantities = {str(k): int(v) for k, v in opening.items()}
        invested_at = pd.Timestamp(origin["opening_date"])
        cash = float(origin["opening_cash"])
        opening_recv = float(nav.get("dividend_receivable", pd.Series([0.])).iloc[0])
        identity = json.dumps(origin, sort_keys=True)
    else:
        fills = strategy.fills
        if fills.empty or not {"trade_date", "side", "filled_qty", "notional", "commission"}.issubset(fills):
            raise ValueError("初始成交明细不完整")
        valid = fills.loc[fills.filled_qty > 0].sort_values("trade_date")
        if valid.empty:
            raise ValueError("尚未建仓")
        invested_at = pd.Timestamp(valid.trade_date.min())
        entry = valid.loc[valid.trade_date == invested_at]
        if entry.side.ne("BUY").any():
            raise ValueError("首批成交含卖出，无法确定初始组合")
        quantities = {str(k): int(v) for k, v in entry.groupby("symbol").filled_qty.sum().items()}
        cash = initial - float((entry.notional + entry.commission).sum())
        opening_recv = 0.
        identity = entry.to_csv(index=False)
    if cash < -.01:
        raise ValueError("首批成交超过初始现金")
    equity = pd.Series(initial, index=dates, dtype=float)
    active = dates[dates >= invested_at]
    equity.loc[active] = cash + opening_recv
    weights = {}
    for symbol, quantity in quantities.items():
        prices = pd.Series(dtype=float)
        if strategy.project_root:
            path = strategy.project_root / "data" / "execution_cache" / f"etf_{symbol}_raw_close.csv"
            prices = _read_price_cache(path, symbol)
        marks = strategy.positions.loc[strategy.positions.symbol.astype(str) == symbol].set_index("date").close
        if not prices.empty:
            overlap = prices.index.intersection(marks.index)
            if ((prices.loc[overlap] - marks.loc[overlap]).abs() > 1e-8).any():
                raise ValueError(f"{symbol} 缓存与持仓价格冲突")
        prices = prices.combine_first(marks)
        selected = prices.reindex(active)
        if selected.isna().any():
            raise ValueError(f"{symbol} 缺少原始价格，无法模拟继续持有")
        equity.loc[active] += selected * quantity
        weights[symbol] = quantity * float(selected.iloc[0]) / initial
        identity += selected.to_csv()
        # Cash distributions are recognized economically on ex-date. No later
        # trades use that cash, so settlement cannot inflate buying power here.
        schedule_path = strategy.project_root / "data" / "execution_cache" / f"etf_{symbol}_dividend_schedule.csv" if strategy.project_root else None
        legacy_path = strategy.project_root / "data" / "execution_cache" / f"etf_{symbol}_cash_dividend.csv" if strategy.project_root else None
        if schedule_path and schedule_path.exists():
            events = pd.read_csv(schedule_path, parse_dates=["ex_date", "record_date"])
        elif legacy_path and legacy_path.exists():
            events = pd.read_csv(legacy_path, parse_dates=["date"]).rename(columns={"date": "ex_date"})
            events["record_date"] = events.ex_date - pd.Timedelta(days=1)
        else:
            raise ValueError(f"{symbol} 缺少完整分红历史，不能假定分红为零")
        identity += events.to_csv(index=False)
        if not events.empty:
            if events[["ex_date", "record_date", "cash_per_share"]].isna().any().any() or events.ex_date.duplicated().any() or (events.cash_per_share < 0).any():
                raise ValueError(f"{symbol} 分红事件无效")
            for row in events.itertuples():
                if row.record_date >= invested_at and (not opening or row.ex_date > invested_at):
                    equity.loc[dates >= row.ex_date] += quantity * float(row.cash_per_share)
    equity /= initial
    label = f"同初始持仓后持有 · {strategy.display_name}"
    return BenchmarkData(key="initial_fills:" + hashlib.sha256((strategy.key + identity + str(tuple(dates))).encode()).hexdigest()[:16],
                         display_name=label, weights=weights, equity=equity, source_project=strategy.project_root or strategy.data_dir,
                         source_strategy_key=strategy.key, method="actual_initial_fills_buy_hold")


def collect_benchmarks(strategies: list[StrategyData]) -> tuple[list[BenchmarkData], list[str]]:
    """Collect and deduplicate configured benchmarks across selected strategy sources."""

    collected: dict[str, BenchmarkData] = {}
    warnings: list[str] = []
    seen_warnings: set[str] = set()
    for strategy in strategies:
        items, item_warnings = load_benchmarks(strategy)
        try:
            items.append(initial_fills_benchmark(strategy))
        except (ValueError, OSError, KeyError) as exc:
            item_warnings.append(f"{strategy.display_name}: 同初始持仓基准不可用：{exc}")
        for item in items:
            collected.setdefault(item.key, item)
        for warning in item_warnings:
            if warning not in seen_warnings:
                warnings.append(warning)
                seen_warnings.add(warning)
    return list(collected.values()), warnings


def benchmark_returns(benchmark: BenchmarkData) -> pd.Series:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.Series(dtype=float)
    returns = equity.pct_change(fill_method=None)
    returns.iloc[0] = equity.iloc[0] - 1.0
    return returns.replace([math.inf, -math.inf], pd.NA).dropna().astype(float)


def benchmark_normalized(benchmark: BenchmarkData) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "normalized"])
    return pd.DataFrame({"date": equity.index, "normalized": equity.to_numpy() * 100.0})


def benchmark_drawdown_curve(benchmark: BenchmarkData) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    running_max = equity.cummax().clip(lower=1.)
    return pd.DataFrame({"date": equity.index, "drawdown": equity / running_max - 1.0})


def benchmark_rolling_return(benchmark: BenchmarkData, window: int = 63) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "rolling_return"])
    rolling = (1 + benchmark_returns(benchmark)).rolling(window).apply(lambda v: v.prod(), raw=True) - 1
    return pd.DataFrame({"date": equity.index, "rolling_return": rolling.to_numpy()}).dropna()


def benchmark_rolling_sharpe(benchmark: BenchmarkData, window: int = 63) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "rolling_sharpe"])
    returns = benchmark_returns(benchmark)
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std(ddof=1)
    rolling = mean / std.replace(0.0, pd.NA) * math.sqrt(TRADING_DAYS)
    return pd.DataFrame({"date": equity.index, "rolling_sharpe": rolling.to_numpy()}).dropna()


def benchmark_metrics(benchmark: BenchmarkData) -> dict[str, float | str | None]:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return {}

    first_date = pd.Timestamp(equity.index[0])
    last_date = pd.Timestamp(equity.index[-1])
    latest_equity = float(equity.iloc[-1])
    total_return = latest_equity - 1.0
    elapsed_days = max((last_date - first_date).days, 0)

    annualized_return = None
    if elapsed_days >= 365 and latest_equity > 0:
        annualized_return = latest_equity ** (365.25 / elapsed_days) - 1.0

    returns = benchmark_returns(benchmark)
    annualized_volatility = None
    sharpe = None
    if len(returns) >= 2:
        std = float(returns.std(ddof=1))
        annualized_volatility = std * math.sqrt(TRADING_DAYS)
        if std > 0:
            sharpe = float(returns.mean()) / std * math.sqrt(TRADING_DAYS)

    drawdown = benchmark_drawdown_curve(benchmark)
    max_drawdown = float(drawdown["drawdown"].min()) if not drawdown.empty else None

    return {
        "benchmark": benchmark.display_name,
        "composition": benchmark.composition,
        "latest_date": last_date.strftime("%Y-%m-%d"),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "annualized_volatility": annualized_volatility,
        "nav_samples": len(equity),
        "return_samples": len(returns),
    }


def excess_return_curve(strategy: StrategyData, benchmark: BenchmarkData, mode: str = "difference") -> pd.DataFrame:
    """Return cumulative strategy excess wealth relative to a benchmark."""

    if strategy.nav.empty or "date" not in strategy.nav.columns or "nav" not in strategy.nav.columns:
        return pd.DataFrame(columns=["date", "excess_return"])

    nav = strategy.nav[["date", "nav"]].copy()
    nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
    nav["nav"] = pd.to_numeric(nav["nav"], errors="coerce")
    nav = nav.dropna().drop_duplicates("date", keep="last").sort_values("date")
    nav = nav[nav["nav"] > 0]
    if nav.empty:
        return pd.DataFrame(columns=["date", "excess_return"])

    initial_cash = _float(strategy.state.get("initial_cash"), 0.0)
    if initial_cash <= 0:
        initial_cash = float(nav["nav"].iloc[0])
    strategy_wealth = nav.set_index("date")["nav"] / initial_cash

    benchmark_wealth = benchmark.equity.dropna().sort_index()
    joined = pd.concat(
        [strategy_wealth.rename("strategy"), benchmark_wealth.rename("benchmark")],
        axis=1,
        join="inner",
    ).dropna()
    joined = joined[joined["benchmark"] > 0]
    if joined.empty:
        return pd.DataFrame(columns=["date", "excess_return"])

    if benchmark.source_strategy_key and benchmark.source_strategy_key != strategy.key:
        return pd.DataFrame(columns=["date", "excess_return"])
    if not strategy_wealth.index.equals(benchmark_wealth.index):
        return pd.DataFrame(columns=["date", "excess_return"])
    relative = (joined["strategy"] - joined["benchmark"] if mode == "difference"
                else joined["strategy"] / joined["benchmark"] - 1.0)
    return pd.DataFrame({"date": relative.index, "excess_return": relative.to_numpy()})
