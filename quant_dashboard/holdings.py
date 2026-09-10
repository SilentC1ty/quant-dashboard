from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .models import StrategyData


@dataclass(slots=True, eq=False)
class HoldingReturnSeries:
    """Price-return history for one currently held symbol.

    The curve starts at the first close of the symbol's current uninterrupted
    holding streak and is therefore a holding-period *price* return. It does not
    attempt to allocate account-level commissions, slippage or cash dividends to
    an individual position.
    """

    symbol: str
    name: str
    start_date: pd.Timestamp
    latest_date: pd.Timestamp
    quantity: float
    current_weight: float | None
    latest_return: float
    curve: pd.DataFrame


def _clean_positions(strategy: StrategyData) -> pd.DataFrame:
    positions = strategy.positions.copy()
    required = {"date", "symbol", "quantity", "close"}
    if positions.empty or not required.issubset(positions.columns):
        return pd.DataFrame()

    positions["date"] = pd.to_datetime(positions["date"], errors="coerce")
    positions["symbol"] = positions["symbol"].astype(str)
    positions["quantity"] = pd.to_numeric(positions["quantity"], errors="coerce")
    positions["close"] = pd.to_numeric(positions["close"], errors="coerce")
    if "weight" in positions.columns:
        positions["weight"] = pd.to_numeric(positions["weight"], errors="coerce")

    positions = positions.dropna(subset=["date", "symbol", "quantity", "close"])
    positions = positions[(positions["quantity"] > 0) & (positions["close"] > 0)]
    return positions.sort_values(["date", "symbol"]).reset_index(drop=True)


def _processed_dates(strategy: StrategyData, latest: pd.Timestamp) -> list[pd.Timestamp]:
    if strategy.nav.empty or "date" not in strategy.nav.columns:
        return []
    dates = pd.to_datetime(strategy.nav["date"], errors="coerce").dropna()
    dates = dates[dates <= latest].drop_duplicates().sort_values()
    return [pd.Timestamp(value) for value in dates]


def _current_streak_start(
    positions: pd.DataFrame,
    processed_dates: list[pd.Timestamp],
    symbol: str,
    latest: pd.Timestamp,
) -> pd.Timestamp:
    symbol_dates = set(
        pd.Timestamp(value)
        for value in positions.loc[positions["symbol"] == symbol, "date"].dropna().unique()
    )

    if not processed_dates:
        symbol_history = sorted(date for date in symbol_dates if date <= latest)
        return symbol_history[0] if symbol_history else latest

    start = latest
    for date in reversed(processed_dates):
        if date > latest:
            continue
        if date in symbol_dates:
            start = date
            continue
        # Once a processed trading day without the symbol is reached, the
        # current uninterrupted holding streak starts after that gap.
        break
    return start


def current_holding_return_series(strategy: StrategyData) -> list[HoldingReturnSeries]:
    """Return price-return curves for every symbol held on the latest snapshot."""

    positions = _clean_positions(strategy)
    if positions.empty:
        return []

    latest = pd.Timestamp(positions["date"].max())
    current = positions.loc[positions["date"] == latest].drop_duplicates("symbol", keep="last")
    processed_dates = _processed_dates(strategy, latest)

    result: list[HoldingReturnSeries] = []
    for _, current_row in current.sort_values("symbol").iterrows():
        symbol = str(current_row["symbol"])
        start = _current_streak_start(positions, processed_dates, symbol, latest)
        history = positions.loc[
            (positions["symbol"] == symbol)
            & (positions["date"] >= start)
            & (positions["date"] <= latest),
            ["date", "close"],
        ].drop_duplicates("date", keep="last").sort_values("date")
        if history.empty:
            continue

        base = float(history["close"].iloc[0])
        if base <= 0:
            continue
        curve = history.copy()
        curve["return"] = curve["close"] / base - 1.0

        weight: float | None = None
        if "weight" in current_row.index and pd.notna(current_row.get("weight")):
            weight = float(current_row["weight"])

        result.append(
            HoldingReturnSeries(
                symbol=symbol,
                name=strategy.names.get(symbol, symbol),
                start_date=pd.Timestamp(curve["date"].iloc[0]),
                latest_date=pd.Timestamp(curve["date"].iloc[-1]),
                quantity=float(current_row["quantity"]),
                current_weight=weight,
                latest_return=float(curve["return"].iloc[-1]),
                curve=curve[["date", "return"]].reset_index(drop=True),
            )
        )

    return result
