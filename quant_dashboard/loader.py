from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .models import StrategyData
from .sources import find_project_root, normalize_path


CSV_FILES = {
    "nav": "nav.csv",
    "positions": "positions.csv",
    "orders": "orders.csv",
    "fills": "fills.csv",
    "cash_events": "cash_events.csv",
}
DATE_COLUMNS = ("date", "signal_date", "trade_date")
NUMERIC_COLUMNS = {
    "cash",
    "market_value",
    "nav",
    "return_since_start",
    "pending_orders",
    "total_commission",
    "total_slippage",
    "total_dividends",
    "quantity",
    "close",
    "weight",
    "target_weight",
    "requested_qty",
    "filled_qty",
    "signal_price",
    "reference_close",
    "fill_price",
    "notional",
    "commission",
    "slippage_cost",
    "cash_per_share",
    "cash_amount",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()

    for column in DATE_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in NUMERIC_COLUMNS.intersection(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    sort_columns = [name for name in DATE_COLUMNS if name in frame.columns]
    if sort_columns:
        frame = frame.sort_values(sort_columns).reset_index(drop=True)
    return frame


def _source_key(path: Path) -> str:
    return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]


def _default_display_name(version: str, frequency: str | None, every: int | None, data_dir: Path) -> str:
    suffix = ""
    if frequency == "W-FRI" and every == 1:
        suffix = "每周"
    elif frequency == "W-FRI" and every == 2:
        suffix = "双周"
    elif frequency == "M" and every == 1:
        suffix = "每月"
    elif frequency and every:
        suffix = f"{frequency} × {every}"

    base = version if version and version != "unknown" else data_dir.name
    return f"{base} · {suffix}" if suffix else base


def load_strategy(data_dir: str | Path, custom_label: str = "") -> StrategyData:
    data_path = normalize_path(data_dir)
    if not data_path.is_dir():
        raise FileNotFoundError(f"数据目录不存在：{data_path}")

    state = _read_json(data_path / "state.json")
    nav = _read_csv(data_path / "nav.csv")
    if not state:
        raise ValueError(f"缺少或无法解析 state.json：{data_path}")
    if nav.empty:
        raise ValueError(f"缺少或无法解析 nav.csv：{data_path}")

    project_root = find_project_root(data_path)
    settings: dict[str, Any] = {}
    universe: dict[str, Any] = {}
    if project_root is not None:
        settings = _read_yaml(project_root / "config" / "settings.yaml")
        universe = _read_yaml(project_root / "config" / "universe.yaml")

    paper_cfg = settings.get("paper", {}) if isinstance(settings.get("paper", {}), dict) else {}
    execution_cfg = paper_cfg.get("execution", {}) if isinstance(paper_cfg.get("execution", {}), dict) else {}
    strategy_version = str(state.get("strategy_version") or paper_cfg.get("strategy_version") or "unknown")
    frequency = execution_cfg.get("frequency")
    every_raw = execution_cfg.get("every")
    try:
        every = int(every_raw) if every_raw is not None else None
    except (TypeError, ValueError):
        every = None

    raw_names = universe.get("names", {}) if isinstance(universe.get("names", {}), dict) else {}
    names = {str(key): str(value) for key, value in raw_names.items()}
    display_name = custom_label.strip() or _default_display_name(
        strategy_version,
        str(frequency) if frequency else None,
        every,
        data_path,
    )

    warnings: list[str] = []
    required_nav = {"date", "nav", "cash"}
    missing_nav = required_nav.difference(nav.columns)
    if missing_nav:
        warnings.append(f"nav.csv 缺少字段：{', '.join(sorted(missing_nav))}")
    if project_root is None:
        warnings.append("未找到 config/settings.yaml；调仓频率和 ETF 名称可能不可用。")

    frames = {name: _read_csv(data_path / filename) for name, filename in CSV_FILES.items() if name != "nav"}

    return StrategyData(
        key=_source_key(data_path),
        source_path=data_path,
        data_dir=data_path,
        project_root=project_root,
        display_name=display_name,
        strategy_version=strategy_version,
        rebalance_frequency=str(frequency) if frequency else None,
        rebalance_every=every,
        settings=settings,
        universe=universe,
        names=names,
        state=state,
        nav=nav,
        positions=frames["positions"],
        orders=frames["orders"],
        fills=frames["fills"],
        cash_events=frames["cash_events"],
        warnings=warnings,
    )
