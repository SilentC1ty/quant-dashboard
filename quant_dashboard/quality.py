from __future__ import annotations

import hashlib
import json
import math

import pandas as pd

from .models import StrategyData


def validate_snapshot(strategy: StrategyData) -> list[str]:
    """Reject broken identities; return explicit limitations for legacy ledgers."""
    nav, state = strategy.nav, strategy.state
    required = {"date", "nav", "cash", "market_value"}
    if not required.issubset(nav):
        raise ValueError("nav.csv 缺少字段：" + ", ".join(sorted(required - set(nav))))
    for column in ("cash", "nav", "market_value", "dividend_receivable"):
        if column in nav and (not nav[column].map(lambda v: pd.notna(v) and math.isfinite(float(v))).all()):
            raise ValueError(f"nav.csv {column} 含无效数值")
    if nav.date.isna().any() or nav.date.duplicated().any() or (nav.nav <= 0).any() or (nav.cash < -.01).any():
        raise ValueError("NAV 日期重复、无效或账户数值越界")
    recv = nav.get("dividend_receivable", pd.Series(0., index=nav.index))
    if ((nav.cash + nav.market_value + recv - nav.nav).abs() > .01).any():
        raise ValueError("NAV 不等于现金 + 持仓市值 + 应收分红")
    latest = nav.iloc[-1]
    if "pending_orders" in nav and int(latest.pending_orders) != len(state.get("pending_orders", [])):
        raise ValueError("state 与 NAV 待成交数量不一致")
    if abs(float(state.get("cash", float("nan"))) - float(latest.cash)) > .01:
        raise ValueError("state 与 NAV 最新现金不一致")
    if state.get("last_processed_date") and pd.Timestamp(state["last_processed_date"]) != latest.date:
        raise ValueError("state 与 NAV 最新日期不一致")
    if "dividend_receivable" in nav and abs(sum(float(e["cash_amount"]) for e in state.get("receivables", {}).values()) - float(latest.dividend_receivable)) > .01:
        raise ValueError("state 应收分红与 NAV 不一致")
    warnings = []
    for key in ("initial_cash", "cash", "total_commission", "total_slippage", "total_dividends"):
        if key not in state or not math.isfinite(float(state[key])):
            raise ValueError(f"state 缺少或含无效数值：{key}")
        if float(state[key]) < 0 or (key == "initial_cash" and float(state[key]) <= 0):
            raise ValueError(f"state 数值越界：{key}")
    initial = float(state["initial_cash"])
    if "return_since_start" in nav and ((nav.nav / initial - 1 - nav.return_since_start).abs() > 1e-8).any():
        raise ValueError("NAV 收益率与初始资金不一致")
    positions = strategy.positions
    if not positions.empty:
        if not {"date", "symbol", "quantity", "close", "market_value"}.issubset(positions):
            raise ValueError("持仓快照字段不完整")
        if positions.duplicated(["date", "symbol"]).any() or (positions.close <= 0).any() or (positions.quantity < 0).any():
            raise ValueError("持仓快照重复或价格/数量越界")
        if ((positions.quantity * positions.close - positions.market_value).abs() > .01).any():
            raise ValueError("持仓数量乘价格不等于市值")
        values = positions.groupby("date").market_value.sum().reindex(nav.date, fill_value=0).to_numpy()
        if (abs(values - nav.market_value.to_numpy()) > .01).any():
            raise ValueError("持仓快照与 NAV 市值不一致或缺少持仓交易日")
        held = positions.loc[positions.date == latest.date]
        quantities = {str(r.symbol): int(r.quantity) for r in held.itertuples() if r.quantity > 0}
        if quantities != {str(k): int(v) for k, v in state.get("holdings", {}).items() if int(v) > 0}:
            raise ValueError("state 与最新持仓数量不一致")
    elif float(latest.market_value) > .01:
        warnings.append("持仓日志缺失，无法核对持仓市值与数量。")
    for state_key, column in (("total_commission", "commission"), ("total_slippage", "slippage_cost")):
        if column in strategy.fills:
            if abs(float(strategy.fills[column].sum()) - float(state[state_key])) > .01:
                raise ValueError(f"成交日志与累计费用不一致：{column}")
        elif float(state[state_key]) > 0:
            warnings.append(f"成交日志缺失 {column}，无法复核累计费用。")
    for key in ("total_commission", "total_slippage", "total_dividends"):
        if key in nav and abs(float(latest[key]) - float(state[key])) > .01:
            raise ValueError(f"state 与 NAV 累计字段不一致：{key}")
    events = strategy.cash_events
    if not events.empty and {"type", "cash_amount"}.issubset(events):
        paid = float(events.loc[events.type.isin(["DIVIDEND", "DIVIDEND_PAYMENT"]), "cash_amount"].sum())
        if abs(paid - float(state["total_dividends"])) > .01:
            raise ValueError("分红到账记录与 state 累计分红不一致")
    elif float(state["total_dividends"]) > 0:
        warnings.append("缺少分红明细，无法复核累计分红。")
    fills = strategy.fills
    confirmed_no_trades = fills.empty and nav.market_value.eq(0).all() and float(state["total_commission"]) == 0 and float(state["total_slippage"]) == 0
    complete_fills = confirmed_no_trades or {"trade_date", "symbol", "side", "filled_qty", "notional", "commission"}.issubset(fills)
    complete_dividends = float(state["total_dividends"]) == 0 or (not events.empty and {"date", "type", "cash_amount"}.issubset(events))
    if complete_fills and complete_dividends:
        origin = state.get("origin", {})
        running_cash = float(origin.get("opening_cash", initial))
        quantities = {str(k): int(v) for k, v in origin.get("opening_holdings", {}).items()}
        changes = []
        for row in fills.to_dict("records"):
            if row["side"] not in ("BUY", "SELL") or float(row["filled_qty"]) < 0 or float(row["notional"]) < 0 or float(row["commission"]) < 0:
                raise ValueError("成交方向、数量或金额越界")
            sign = 1 if row["side"] == "BUY" else -1
            changes.append((pd.Timestamp(row["trade_date"]), -sign * float(row["notional"]) - float(row["commission"]),
                            str(row["symbol"]), sign * float(row["filled_qty"])))
        for row in events.to_dict("records"):
            if row.get("type") in ("DIVIDEND", "DIVIDEND_PAYMENT"):
                changes.append((pd.Timestamp(row["date"]), float(row["cash_amount"]), "", 0.))
        changes.sort(key=lambda row: row[0])
        index = 0
        for row in nav.itertuples():
            while index < len(changes) and changes[index][0] <= row.date:
                _, amount, symbol, quantity = changes[index]
                running_cash += amount
                if symbol:
                    quantities[symbol] = quantities.get(symbol, 0) + quantity
                index += 1
            if abs(running_cash - float(row.cash)) > .01:
                raise ValueError(f"成交及分红现金流与 NAV 不一致：{row.date:%Y-%m-%d}")
            if not positions.empty:
                held = positions.loc[positions.date == row.date]
                actual = {str(p.symbol): int(p.quantity) for p in held.itertuples() if p.quantity > 0}
                if actual != {k: v for k, v in quantities.items() if v != 0}:
                    raise ValueError(f"成交数量与持仓快照不一致：{row.date:%Y-%m-%d}")
        if index != len(changes):
            raise ValueError("成交或现金事件晚于最新 NAV")
    else:
        warnings.append("成交金额或分红明细不足，未完成逐日现金流复核。")
    if strategy.project_root:
        # A complete local research chain supplies observed exchange sessions;
        # do not silently bridge a dropped NAV row when those dates are known.
        adjust = str(strategy.universe.get("adjust") or "none")
        asset_type = str(strategy.universe.get("asset_type") or "etf")
        caches = list((strategy.project_root / "data" / "cache").glob(f"{asset_type}_*_{adjust}.csv"))
        if caches:
            raw_dates = pd.read_csv(caches[0], usecols=["date"])
            dates = pd.to_datetime(raw_dates.date, errors="coerce")
            if dates.isna().any():
                raise ValueError("本地行情缓存日期无效")
            expected = pd.DatetimeIndex(dates[(dates >= nav.date.min()) & (dates <= nav.date.max())])
            if len(expected.difference(pd.DatetimeIndex(nav.date))):
                raise ValueError("NAV 缺少本地行情已知交易日")
    paper = strategy.settings.get("paper", {})
    if state.get("config_fingerprint") and paper:
        payload = {"strategy_version": paper.get("strategy_version", "v0.3.0"), "strategy": paper.get("strategy", {}),
                   "execution": paper.get("execution", {}), "portfolio": strategy.settings.get("portfolio", {}),
                   "cost": strategy.settings.get("cost", {}), "initial_cash": float(paper.get("initial_cash", 100000.)),
                   "lot_size": int(paper.get("lot_size", 100)), "minimum_commission": float(paper.get("minimum_commission", 5.)),
                   "fill_price": paper.get("fill_price", "next_close"), "credit_dividends": bool(paper.get("credit_dividends", True)),
                   "tickers": [str(s) for s in strategy.universe.get("tickers", [])]}
        for key in ("accounting_mode", "execution_policy"):
            if key in paper:
                payload[key] = paper[key]
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()[:16]
        if fingerprint != state["config_fingerprint"]:
            raise ValueError("冻结配置指纹不匹配；请使用该实绩对应的历史配置")
    else:
        warnings.append("缺少冻结配置指纹，无法确认策略规则归属。")
    if not state.get("accounting_mode") or state.get("accounting_mode") == "legacy_ex_date_cash":
        warnings.append("旧版分红在除息日计入现金；到账前的可用现金可能高估，NAV 已包含分红。")
    return warnings
