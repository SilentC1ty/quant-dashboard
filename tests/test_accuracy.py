import json
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from quant_dashboard.benchmarks import initial_fills_benchmark, excess_return_curve, collect_benchmarks, benchmark_returns
from quant_dashboard.contributions import symbol_contributions
from quant_dashboard.loader import load_strategy
from quant_dashboard.metrics import strategy_metrics, daily_returns, drawdown_curve, rolling_return
from quant_dashboard.models import StrategyData
from quant_dashboard.orders import current_orders
from test_dashboard import _write_minimal_project, _enable_benchmarks


def account(tmp_path):
    return StrategyData(key="one", source_path=tmp_path, data_dir=tmp_path, project_root=tmp_path,
                        display_name="one", strategy_version="v2", rebalance_frequency="W-FRI", rebalance_every=1,
                        state={"initial_cash": 1000., "cash": 600., "pending_orders": []})


@pytest.mark.parametrize("quantity,queued,fill_status,expected", [
    (100, False, "FILLED", "FILLED"), (0, True, "", "PENDING"),
    (40, False, "PARTIAL", "PARTIAL_CLOSED"), (40, True, "PARTIAL", "PARTIAL_PENDING"),
    (0, False, "REJECTED", "REJECTED"), (0, False, "", "UNKNOWN"),
    (100, True, "FILLED", "CONFLICT"), (101, False, "FILLED", "CONFLICT")])
def test_order_status_comes_from_fills_and_current_queue(tmp_path, quantity, queued, fill_status, expected):
    strategy = account(tmp_path)
    creation = {"order_id": "P1", "symbol": "R", "side": "BUY", "requested_qty": 100, "status": "PENDING"}
    strategy.orders = pd.DataFrame([creation])
    if queued:
        strategy.state["pending_orders"] = [creation]
    if fill_status:
        strategy.fills = pd.DataFrame([{**creation, "filled_qty": quantity, "status": fill_status}])
    view = current_orders(strategy)
    assert view.current_status.iloc[0] == expected
    assert strategy.orders.status.iloc[0] == "PENDING"
    assert view.strategy_key.iloc[0] == "one"


@pytest.mark.parametrize("change", ["bad_number", "cash_mismatch", "position_mismatch", "bad_file", "bad_config", "duplicate_nav"])
def test_corrupt_data_is_not_an_empty_healthy_account(tmp_path, change):
    path = _write_minimal_project(tmp_path / "project")
    if change == "bad_file":
        (path / "fills.csv").write_text('"unterminated', encoding="utf-8")
    elif change == "bad_config":
        (path.parent.parent / "config" / "settings.yaml").write_text("broken: [", encoding="utf-8")
    elif change == "position_mismatch":
        frame = pd.read_csv(path / "positions.csv")
        frame.loc[0, "close"] = 0
        frame.to_csv(path / "positions.csv", index=False)
    elif change == "cash_mismatch":
        state = json.loads((path / "state.json").read_text())
        state["cash"] = 1
        (path / "state.json").write_text(json.dumps(state))
    else:
        frame = pd.read_csv(path / "nav.csv")
        if change == "bad_number":
            frame["nav"] = frame["nav"].astype(float)
            frame.loc[0, "nav"] = float("inf")
        else:
            frame = pd.concat([frame, frame.iloc[[0]]])
        frame.to_csv(path / "nav.csv", index=False)
    with pytest.raises(ValueError):
        load_strategy(path)


def test_short_sample_first_day_costs_and_drawdown_are_consistent(tmp_path):
    strategy = account(tmp_path)
    strategy.state.update(total_commission=1., total_slippage=0., total_dividends=0.)
    strategy.nav = pd.DataFrame({"date": pd.to_datetime(["2026-01-02", "2026-02-02"]), "nav": [999., 1010.], "cash": [599., 610.]})
    metrics = strategy_metrics(strategy)
    assert metrics["annualized_return"] is None
    assert metrics["return_samples"] == 2
    returns = daily_returns(strategy)
    assert returns.iloc[0] == pytest.approx(-.001)
    assert (1 + returns).prod() == pytest.approx(1.01)
    assert drawdown_curve(strategy).drawdown.iloc[0] == pytest.approx(-.001)
    assert rolling_return(strategy, 2).rolling_return.iloc[-1] == pytest.approx(.01)


def test_same_initial_fills_baseline_includes_cost_dividends_and_cash(tmp_path):
    strategy = account(tmp_path)
    dates = pd.to_datetime(["2026-09-17", "2026-09-18", "2026-09-23"])
    strategy.nav = pd.DataFrame({"date": dates, "nav": [999., 1009., 1019.]})
    strategy.fills = pd.DataFrame([{"symbol": "B", "side": "BUY", "trade_date": dates[0], "filled_qty": 100,
                                    "notional": 400., "commission": 1., "slippage_cost": .2}])
    strategy.positions = pd.DataFrame({"date": dates, "symbol": "B", "close": [4., 4., 4.1], "market_value": [400., 400., 410.]})
    root = tmp_path / "data" / "execution_cache"
    root.mkdir(parents=True)
    pd.DataFrame({"date": [dates[1]], "cash_per_share": [.1]}).to_csv(root / "etf_B_cash_dividend.csv", index=False)
    benchmark = initial_fills_benchmark(strategy)
    assert benchmark.equity.tolist() == pytest.approx([.999, 1.009, 1.019])
    assert (1 + benchmark_returns(benchmark)).prod() == pytest.approx(1.019)
    strategy.cash_events = pd.DataFrame([{"date": dates[1], "symbol": "B", "type": "DIVIDEND_ACCRUAL", "cash_amount": 10.},
                                         {"date": dates[2], "symbol": "B", "type": "DIVIDEND_PAYMENT", "cash_amount": 10.}])
    assert symbol_contributions(strategy).net_pnl.iloc[0] == pytest.approx(19.)
    strategy.nav.loc[2, "nav"] = 1029.
    assert excess_return_curve(strategy, benchmark).excess_return.iloc[-1] == pytest.approx(.01)
    assert excess_return_curve(strategy, benchmark, "relative").excess_return.iloc[-1] == pytest.approx(1.029 / 1.019 - 1)
    strategy.key = "other"
    assert excess_return_curve(strategy, benchmark).empty


def test_benchmark_identity_keeps_distinct_sources_and_periods(tmp_path):
    first = _write_minimal_project(tmp_path / "a")
    second = _write_minimal_project(tmp_path / "b")
    _enable_benchmarks(tmp_path / "a")
    _enable_benchmarks(tmp_path / "b")
    items, _ = collect_benchmarks([load_strategy(first), load_strategy(second)])
    assert len(items) == 4
    assert len(set(item.key for item in items)) == 4


def test_incomplete_manifest_and_missing_exchange_session_are_errors(tmp_path):
    path = _write_minimal_project(tmp_path / "quant")
    (path / "ledger_manifest.json").write_text(json.dumps({"files": {"state.json": "wrong"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="完整"):
        load_strategy(path)
    (path / "ledger_manifest.json").write_text(json.dumps({"files": {"state.json": hashlib.sha256((path / "state.json").read_bytes()).hexdigest()}}), encoding="utf-8")
    _enable_benchmarks(tmp_path / "quant")
    cache = tmp_path / "quant/data/cache/etf_510300_qfq.csv"
    frame = pd.read_csv(cache)
    frame.loc[len(frame)] = ["2026-01-05", 101.]
    frame.to_csv(cache, index=False)
    with pytest.raises(ValueError, match="交易日"):
        load_strategy(path)


def test_daily_cashflow_reconciliation_catches_bad_execution_amount(tmp_path):
    path = _write_minimal_project(tmp_path / "quant")
    fills = pd.read_csv(path / "fills.csv")
    fills["notional"] = 79993.
    fills.to_csv(path / "fills.csv", index=False)
    pd.DataFrame([{"date": "2026-01-12", "type": "DIVIDEND", "symbol": "510300", "cash_amount": 5.}]).to_csv(path / "cash_events.csv", index=False)
    assert load_strategy(path).state["cash"] == 20000.
    fills["notional"] += 1.
    fills.to_csv(path / "fills.csv", index=False)
    with pytest.raises(ValueError, match="现金流"):
        load_strategy(path)
