from __future__ import annotations

import pandas as pd

from .models import StrategyData


def symbol_contributions(strategy: StrategyData) -> pd.DataFrame:
    """Dollar contribution incl. realized P&L; slippage is already in notional."""
    fills = strategy.fills
    if not fills.empty and not {"symbol", "side", "notional", "commission", "filled_qty"}.issubset(fills):
        raise ValueError("成交明细不完整，无法计算单标的净贡献")
    events = strategy.cash_events
    if events.empty and (float(strategy.state.get("total_dividends", 0)) > 0 or strategy.state.get("receivables")):
        raise ValueError("分红明细缺失，无法计算完整账户净贡献")
    if not events.empty and not {"symbol", "type", "cash_amount"}.issubset(events):
        raise ValueError("分红明细不完整，无法计算单标的净贡献")
    if strategy.positions.empty and strategy.state.get("holdings"):
        raise ValueError("持仓快照缺失，无法计算账户净贡献")
    symbols = set(strategy.positions.get("symbol", pd.Series(dtype=str)).astype(str))
    symbols.update(fills.get("symbol", pd.Series(dtype=str)).astype(str))
    latest = strategy.latest_date
    origin = strategy.state.get("origin", {})
    rows = []
    for symbol in sorted(symbols):
        history = strategy.positions.loc[strategy.positions.symbol.astype(str) == symbol]
        current = history.loc[history.date == latest]
        value = float(current.market_value.sum()) if "market_value" in current else 0.
        trades = fills.loc[fills.symbol.astype(str) == symbol] if "symbol" in fills else pd.DataFrame()
        cashflow = 0.
        if not trades.empty:
            cashflow = float((trades.notional.where(trades.side.eq("SELL"), -trades.notional) - trades.commission).sum())
        dividends = 0.
        if not events.empty:
            dividends = float(events.loc[(events.symbol.astype(str) == symbol) & events.type.isin(["DIVIDEND", "DIVIDEND_ACCRUAL"]), "cash_amount"].sum())
        opening = 0.
        if origin.get("opening_holdings", {}).get(symbol, 0):
            entry = history.loc[history.date == pd.Timestamp(origin["opening_date"])]
            if entry.empty:
                raise ValueError("缺少新实验盘期初持仓价格")
            opening = float(entry.market_value.sum())
        pnl = value + cashflow + dividends - opening
        rows.append({"symbol": symbol, "name": strategy.names.get(symbol, symbol), "net_pnl": pnl,
                     "contribution_pp": pnl / float(strategy.state["initial_cash"]) * 100., "dividends_earned": dividends})
    return pd.DataFrame(rows)


def holding_total_return(strategy: StrategyData, symbol: str, start: pd.Timestamp) -> pd.DataFrame:
    """Reinvested dividend-inclusive return of one share over the current streak."""
    prices = strategy.positions.loc[(strategy.positions.symbol.astype(str) == symbol) & (strategy.positions.date >= start)].set_index("date").close.sort_index()
    if prices.empty:
        return pd.DataFrame(columns=["date", "return"])
    if strategy.project_root is None:
        raise ValueError("缺少分红历史")
    root = strategy.project_root / "data" / "execution_cache"
    schedule = root / f"etf_{symbol}_dividend_schedule.csv"
    legacy = root / f"etf_{symbol}_cash_dividend.csv"
    if schedule.exists():
        events = pd.read_csv(schedule, parse_dates=["ex_date"])
        distributions = events.groupby("ex_date").cash_per_share.sum()
    elif legacy.exists():
        events = pd.read_csv(legacy, parse_dates=["date"])
        distributions = events.groupby("date").cash_per_share.sum()
    else:
        raise ValueError(f"{symbol} 分红历史不可用；价格收益仍可查看")
    if distributions.isna().any() or (distributions < 0).any():
        raise ValueError("无效分红数据")
    returns = (prices + distributions.reindex(prices.index, fill_value=0)) / prices.shift(1)
    returns.iloc[0] = 1.
    return pd.DataFrame({"date": prices.index, "return": returns.cumprod().to_numpy() - 1})
