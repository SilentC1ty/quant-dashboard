from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .models import StrategyData
from .sources import find_project_root, normalize_path
from .quality import validate_snapshot


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
    "dividend_receivable",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"配置文件解析失败：{path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"配置内容不是对象：{path}")
    return raw


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"状态文件解析失败：{path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"状态内容不是对象：{path}")
    return raw


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path, dtype={"symbol": str, "order_id": str})
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise ValueError(f"CSV 无法解析：{path.name}") from exc

    for column in DATE_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
            if frame[column].isna().any():
                raise ValueError(f"{path.name} 含无效日期：{column}")
    for column in NUMERIC_COLUMNS.intersection(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        nullable = column == "fill_price" and "status" in frame
        bad = frame[column].isna() | frame[column].isin([float("inf"), -float("inf")])
        if nullable:
            bad &= frame.status.ne("REJECTED")
        if bad.any():
            raise ValueError(f"{path.name} 含无效数值：{column}")

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

    manifest_path = data_path / "ledger_manifest.json"
    manifest_before = manifest_path.read_bytes() if manifest_path.exists() else None
    if manifest_before is not None:
        manifest = json.loads(manifest_before)
        for name, expected in manifest.get("files", {}).items():
            if name not in ("state.json", *CSV_FILES.values()):
                raise ValueError("账本清单包含未知文件")
            path = data_path / name
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("账本尚未完整提交或文件已变化；请刷新重试")

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

    strategy = StrategyData(
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
    strategy.warnings.extend(validate_snapshot(strategy))
    for name, filename in CSV_FILES.items():
        if name != "nav" and not (data_path / filename).exists():
            strategy.warnings.append(f"{filename} 不存在；对应明细不可用。")
    if manifest_before is not None and manifest_path.read_bytes() != manifest_before:
        raise ValueError("读取期间账本发生更新；请刷新重试")
    # Check the same bytes again after reading, so a writer cannot expose a mixed snapshot.
    if manifest_before is not None:
        for name, expected in manifest["files"].items():
            if hashlib.sha256((data_path / name).read_bytes()).hexdigest() != expected:
                raise ValueError("读取期间账本发生更新；请刷新重试")
    return strategy
