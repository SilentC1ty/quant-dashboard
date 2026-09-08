from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quant_dashboard.benchmarks import (
    benchmark_metrics,
    benchmark_normalized,
    collect_benchmarks,
)
from quant_dashboard.loader import load_strategy
from quant_dashboard.metrics import strategy_metrics
from quant_dashboard.models import StrategyData
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
        'asset_type: etf\nadjust: qfq\nnames:\n  "510300": 沪深300ETF\n  "511010": 国债ETF\n',
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


def _enable_benchmarks(root: Path) -> None:
    settings_path = root / "config" / "settings.yaml"
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8")
        + "cost:\n"
        + "  commission: 0.0003\n"
        + "  slippage: 0.0005\n"
        + "benchmark:\n"
        + '  csi300_symbol: "510300"\n'
        + "  balanced_weights:\n"
        + '    "510300": 0.60\n'
        + '    "511010": 0.40\n',
        encoding="utf-8",
    )
    cache_dir = root / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "etf_510300_qfq.csv").write_text(
        "date,close\n2026-01-02,100\n2026-02-02,110\n",
        encoding="utf-8",
    )
    (cache_dir / "etf_511010_qfq.csv").write_text(
        "date,close\n2026-01-02,100\n2026-02-02,102\n",
        encoding="utf-8",
    )


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
    assert metrics["total_return"] == pytest.approx(0.05)
    assert metrics["trades"] == 1
    assert metrics["total_cost"] == pytest.approx(20.0)


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


def test_strategy_data_equality_never_compares_dataframes(tmp_path: Path) -> None:
    frame = pd.DataFrame({"nav": [100000.0, 101000.0]})
    common = {
        "source_path": tmp_path,
        "data_dir": tmp_path,
        "project_root": None,
        "display_name": "test",
        "strategy_version": "v-test",
        "rebalance_frequency": "W-FRI",
        "rebalance_every": 1,
        "nav": frame,
    }
    first = StrategyData(key="first", **common)
    second = StrategyData(key="second", **common)

    assert (first == first) is True
    assert (first == second) is False


def test_benchmarks_load_from_local_quant_cache(tmp_path: Path) -> None:
    root = tmp_path / "quant"
    data_dir = _write_minimal_project(root)
    _enable_benchmarks(root)
    strategy = load_strategy(data_dir)

    benchmarks, warnings = collect_benchmarks([strategy, strategy])
    assert warnings == []
    assert len(benchmarks) == 2

    balanced = next(item for item in benchmarks if len(item.weights) == 2)
    csi300 = next(item for item in benchmarks if item.weights == {"510300": 1.0})

    balanced_metrics = benchmark_metrics(balanced)
    csi_metrics = benchmark_metrics(csi300)
    assert balanced_metrics["total_return"] == pytest.approx(1.068 / 1.0008 - 1.0)
    assert csi_metrics["total_return"] == pytest.approx(1.1 / 1.0008 - 1.0)

    normalized = benchmark_normalized(csi300)
    assert normalized["normalized"].iloc[0] == pytest.approx(100 / 1.0008)
    assert normalized["normalized"].iloc[-1] == pytest.approx(110 / 1.0008)
