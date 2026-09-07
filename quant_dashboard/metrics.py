from __future__ import annotations

import math

import pandas as pd

from .models import StrategyData


TRADING_DAYS = 252


def clean_nav(strategy: StrategyData) -> pd.DataFrame:
    nav = strategy.nav.copy()
    if nav.empty or "date" not in nav.columns or "nav" not in nav.columns:
        return pd.DataFrame(columns=["date", "nav"])
    nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
    nav["nav"] = pd.to_numeric(nav["nav"], errors="coerce")
    nav = nav.dropna(subset=["date", "nav"])
    nav = nav[nav["nav"] > 0].drop_duplicates("date", keep="last").sort_values("date")
    return nav.reset_index(drop=True)


def daily_returns(strategy: StrategyData) -> pd.Series:
    nav = clean_nav(strategy)
    if len(nav) < 2:
        return pd.Series(dtype=float)
    values = nav.set_index("date")["nav"].pct_change().dropna()
    return values.replace([math.inf, -math.inf], pd.NA).dropna().astype(float)


def normalized_nav(strategy: StrategyData) -> pd.DataFrame:
    nav = clean_nav(strategy)
    if nav.empty:
        return pd.DataFrame(columns=["date", "normalized"])
    initial_cash = float(strategy.state.get("initial_cash") or 0.0)
    base = initial_cash if initial_cash > 0 else float(nav["nav"].iloc[0])
    out = nav[["date", "nav"]].copy()
    out["normalized"] = out["nav"] / base * 100.0
    return out[["date", "normalized"]]


def drawdown_curve(strategy: StrategyData) -> pd.DataFrame:
    nav = clean_nav(strategy)
    if nav.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    running_max = nav["nav"].cummax()
    out = nav[["date"]].copy()
    out["drawdown"] = nav["nav"] / running_max - 1.0
    return out


def rolling_return(strategy: StrategyData, window: int = 63) -> pd.DataFrame:
    nav = clean_nav(strategy)
    if nav.empty:
        return pd.DataFrame(columns=["date", "rolling_return"])
    out = nav[["date"]].copy()
    out["rolling_return"] = nav["nav"].pct_change(window)
    return out.dropna()


def rolling_sharpe(strategy: StrategyData, window: int = 63) -> pd.DataFrame:
    nav = clean_nav(strategy)
    if nav.empty:
        return pd.DataFrame(columns=["date", "rolling_sharpe"])
    returns = nav["nav"].pct_change()
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std(ddof=1)
    out = nav[["date"]].copy()
    out["rolling_sharpe"] = mean / std.replace(0.0, pd.NA) * math.sqrt(TRADING_DAYS)
    return out.dropna()


def _latest_numeric(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _filled_trade_count(strategy: StrategyData) -> int:
    fills = strategy.fills
    if fills.empty:
        return 0
    if "filled_qty" in fills.columns:
        qty = pd.to_numeric(fills["filled_qty"], errors="coerce").fillna(0)
        return int((qty > 0).sum())
    return int(len(fills))


def _current_position_count(strategy: StrategyData) -> int:
    positions = strategy.positions
    if positions.empty or "date" not in positions.columns:
        holdings = strategy.state.get("holdings", {})
        return len([qty for qty in holdings.values() if float(qty) > 0]) if isinstance(holdings, dict) else 0
    dates = pd.to_datetime(positions["date"], errors="coerce")
    if dates.dropna().empty:
        return 0
    latest = dates.max()
    current = positions.loc[dates == latest]
    if "quantity" in current.columns:
        qty = pd.to_numeric(current["quantity"], errors="coerce").fillna(0)
        return int((qty > 0).sum())
    return int(len(current))


def strategy_metrics(strategy: StrategyData) -> dict[str, float | int | str | None]:
    nav = clean_nav(strategy)
    if nav.empty:
        return {}

    latest_nav = float(nav["nav"].iloc[-1])
    initial_cash = float(strategy.state.get("initial_cash") or 0.0)
    if initial_cash <= 0:
        initial_cash = float(nav["nav"].iloc[0])
    total_return = latest_nav / initial_cash - 1.0

    first_date = pd.Timestamp(nav["date"].iloc[0])
    last_date = pd.Timestamp(nav["date"].iloc[-1])
    elapsed_days = max((last_date - first_date).days, 0)
    annualized_return = None
    if elapsed_days >= 30 and latest_nav > 0 and initial_cash > 0:
        annualized_return = (latest_nav / initial_cash) ** (365.25 / elapsed_days) - 1.0

    returns = daily_returns(strategy)
    annualized_volatility = None
    sharpe = None
    if len(returns) >= 2:
        std = float(returns.std(ddof=1))
        annualized_volatility = std * math.sqrt(TRADING_DAYS)
        if std > 0:
            sharpe = float(returns.mean()) / std * math.sqrt(TRADING_DAYS)

    drawdown = drawdown_curve(strategy)
    max_drawdown = float(drawdown["drawdown"].min()) if not drawdown.empty else None
    latest_cash = _latest_numeric(nav, "cash")
    cash_weight = latest_cash / latest_nav if latest_cash is not None and latest_nav > 0 else None

    commission = float(strategy.state.get("total_commission") or 0.0)
    slippage = float(strategy.state.get("total_slippage") or 0.0)
    dividends = float(strategy.state.get("total_dividends") or 0.0)

    return {
        "strategy": strategy.display_name,
        "version": strategy.strategy_version,
        "execution": strategy.execution_label,
        "latest_date": last_date.strftime("%Y-%m-%d"),
        "nav": latest_nav,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "annualized_volatility": annualized_volatility,
        "trades": _filled_trade_count(strategy),
        "positions": _current_position_count(strategy),
        "commission": commission,
        "slippage": slippage,
        "total_cost": commission + slippage,
        "dividends": dividends,
        "cash": latest_cash,
        "cash_weight": cash_weight,
    }
