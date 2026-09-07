from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(slots=True)
class StrategyData:
    key: str
    source_path: Path
    data_dir: Path
    project_root: Path | None
    display_name: str
    strategy_version: str
    rebalance_frequency: str | None
    rebalance_every: int | None
    settings: dict[str, Any] = field(default_factory=dict)
    universe: dict[str, Any] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    nav: pd.DataFrame = field(default_factory=pd.DataFrame)
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)
    orders: pd.DataFrame = field(default_factory=pd.DataFrame)
    fills: pd.DataFrame = field(default_factory=pd.DataFrame)
    cash_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)

    @property
    def latest_date(self) -> pd.Timestamp | None:
        if self.nav.empty or "date" not in self.nav.columns:
            return None
        values = pd.to_datetime(self.nav["date"], errors="coerce").dropna()
        return values.max() if not values.empty else None

    @property
    def execution_label(self) -> str:
        frequency = self.rebalance_frequency or "-"
        every = self.rebalance_every
        if frequency == "W-FRI" and every == 1:
            return "每周"
        if frequency == "W-FRI" and every == 2:
            return "双周"
        if frequency == "M" and every == 1:
            return "每月"
        if every:
            return f"每 {every} 个 {frequency} 周期"
        return frequency
