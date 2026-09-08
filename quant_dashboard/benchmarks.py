from __future__ import annotations

import json
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
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.Series(dtype=float, name=symbol)
    if "date" not in raw.columns or "close" not in raw.columns:
        return pd.Series(dtype=float, name=symbol)

    frame = raw[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna().drop_duplicates("date", keep="last").sort_values("date")
    frame = frame[frame["close"] > 0]
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
    if not definitions:
        return [], []

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
            price = _read_price_cache(cache_path, symbol)
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

        try:
            equity = _build_buy_and_hold(prices, weights, commission, slippage, label)
        except ValueError as exc:
            warnings.append(f"{strategy.display_name}: {label} 无法构造：{exc}")
            continue

        loaded.append(
            BenchmarkData(
                key=key,
                display_name=label,
                weights=weights,
                equity=equity,
                source_project=strategy.project_root,
            )
        )

    return loaded, warnings


def collect_benchmarks(strategies: list[StrategyData]) -> tuple[list[BenchmarkData], list[str]]:
    """Collect and deduplicate configured benchmarks across selected strategy sources."""

    collected: dict[str, BenchmarkData] = {}
    warnings: list[str] = []
    seen_warnings: set[str] = set()
    for strategy in strategies:
        items, item_warnings = load_benchmarks(strategy)
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
    running_max = equity.cummax()
    return pd.DataFrame({"date": equity.index, "drawdown": equity / running_max - 1.0})


def benchmark_rolling_return(benchmark: BenchmarkData, window: int = 63) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "rolling_return"])
    rolling = equity.pct_change(window)
    return pd.DataFrame({"date": equity.index, "rolling_return": rolling.to_numpy()}).dropna()


def benchmark_rolling_sharpe(benchmark: BenchmarkData, window: int = 63) -> pd.DataFrame:
    equity = benchmark.equity.dropna().sort_index()
    if equity.empty:
        return pd.DataFrame(columns=["date", "rolling_sharpe"])
    returns = equity.pct_change(fill_method=None)
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
    if elapsed_days >= 30 and latest_equity > 0:
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
    }


def excess_return_curve(strategy: StrategyData, benchmark: BenchmarkData) -> pd.DataFrame:
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

    relative = joined["strategy"] / joined["benchmark"] - 1.0
    return pd.DataFrame({"date": relative.index, "excess_return": relative.to_numpy()})
