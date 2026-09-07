from __future__ import annotations

import json
from pathlib import Path

from quant_dashboard.loader import load_strategy
from quant_dashboard.metrics import strategy_metrics
from quant_dashboard.sources import SourceRegistry, discover_strategy_dirs


def _write_minimal_project(root: Path, state_dir: str = "data/paper") -> Path:
    (root / "config").mkdir(parents=True)
    data_dir = root / state_dir
    data_dir.mkdir(parents=True)
    (root / "config" / "settings.yaml").write_text(
        "paper:\n  strategy_version: v0.3-test\n  state_dir: " + state_dir + "\n  execution:\n    frequency: W-FRI\n    every: 2\n",
        encoding="utf-8",
    )
    (root / "config" / "universe.yaml").write_text(
        'names:\n  "510300": 沪深300ETF\n',
        encoding="utf-8",
    )
    (data_dir / "state.json").write_text(
        json.dumps(
            {
                "initial_cash": 100000.0,
                "cash": 20000.0,
                "holdings": {"510300": 1000},
                "strategy_version": "v0.3-test",
                "total_commission": 12.0,
                "total_slippage": 8.0,
                "total_dividends": 5.0,
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "nav.csv").write_text(
        "date,cash,market_value,nav,return_since_start\n"
        "2026-01-02,100000,0,100000,0\n"
        "2026-02-02,20000,85000,105000,0.05\n",
        encoding="utf-8",
    )
    (data_dir / "positions.csv").write_text(
        "date,symbol,quantity,close,market_value,weight,target_weight\n"
        "2026-02-02,510300,1000,85,85000,0.8095238,0.8\n",
        encoding="utf-8",
    )
    (data_dir / "fills.csv").write_text(
        "trade_date,symbol,side,filled_qty,commission,slippage_cost,status\n"
        "2026-01-05,510300,BUY,1000,12,8,FILLED\n",
        encoding="utf-8",
    )
    return data_dir


def test_discover_project_and_load_metadata(tmp_path: Path) -> None:
    data_dir = _write_minimal_project(tmp_path / "quant")
    found = discover_strategy_dirs(tmp_path / "quant")
    assert found == [data_dir.resolve()]

    strategy = load_strategy(data_dir)
    assert strategy.strategy_version == "v0.3-test"
    assert strategy.rebalance_every == 2
    assert strategy.execution_label == "双周"
    assert strategy.names["510300"] == "沪深300ETF"

    metrics = strategy_metrics(strategy)
    assert metrics["total_return"] == 0.05
    assert metrics["trades"] == 1
    assert metrics["total_cost"] == 20.0


def test_recursive_discovery_and_registry(tmp_path: Path) -> None:
    first = _write_minimal_project(tmp_path / "a", "data/paper")
    second = _write_minimal_project(tmp_path / "b", "data/paper-weekly")

    found = discover_strategy_dirs(tmp_path, recursive=True)
    assert set(found) == {first.resolve(), second.resolve()}

    registry = SourceRegistry(tmp_path / "registry.json")
    assert registry.add(found) == 2
    assert registry.add(found) == 0
    assert len(registry.load()) == 2

    registry.update_label(first, "双周")
    labels = {item["path"]: item["label"] for item in registry.load()}
    assert labels[str(first.resolve())] == "双周"

    registry.remove(second)
    assert len(registry.load()) == 1
