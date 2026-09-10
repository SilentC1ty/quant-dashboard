from pathlib import Path

import pandas as pd
import pytest

from quant_dashboard.holdings import current_holding_return_series
from quant_dashboard.models import StrategyData


def _strategy(tmp_path: Path) -> StrategyData:
    nav = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-04", "2026-09-07", "2026-09-08", "2026-09-09"]),
            "nav": [100000, 100000, 101000, 102000],
        }
    )
    positions = pd.DataFrame(
        [
            # 510880 was held, exited, then re-entered. The current streak must
            # reset on 2026-09-08 instead of using the older 2026-09-04 close.
            {"date": "2026-09-04", "symbol": "510880", "quantity": 100, "close": 5.0, "weight": 0.2},
            {"date": "2026-09-08", "symbol": "510880", "quantity": 100, "close": 6.0, "weight": 0.4},
            {"date": "2026-09-09", "symbol": "510880", "quantity": 100, "close": 6.6, "weight": 0.42},
            # 511010 is continuously held from 2026-09-07.
            {"date": "2026-09-07", "symbol": "511010", "quantity": 200, "close": 100.0, "weight": 0.3},
            {"date": "2026-09-08", "symbol": "511010", "quantity": 200, "close": 101.0, "weight": 0.28},
            {"date": "2026-09-09", "symbol": "511010", "quantity": 200, "close": 102.0, "weight": 0.27},
        ]
    )
    positions["date"] = pd.to_datetime(positions["date"])
    return StrategyData(
        key="test",
        source_path=tmp_path,
        data_dir=tmp_path,
        project_root=None,
        display_name="test",
        strategy_version="v-test",
        rebalance_frequency="W-FRI",
        rebalance_every=1,
        names={"510880": "红利ETF", "511010": "国债ETF"},
        nav=nav,
        positions=positions,
    )


def test_current_holding_returns_reset_after_position_gap(tmp_path: Path) -> None:
    items = {item.symbol: item for item in current_holding_return_series(_strategy(tmp_path))}

    red = items["510880"]
    assert red.name == "红利ETF"
    assert red.start_date == pd.Timestamp("2026-09-08")
    assert red.latest_date == pd.Timestamp("2026-09-09")
    assert red.current_weight == pytest.approx(0.42)
    assert red.latest_return == pytest.approx(0.10)
    assert red.curve["return"].tolist() == pytest.approx([0.0, 0.10])

    bond = items["511010"]
    assert bond.start_date == pd.Timestamp("2026-09-07")
    assert bond.latest_return == pytest.approx(0.02)
    assert bond.current_weight == pytest.approx(0.27)
