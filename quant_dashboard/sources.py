from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


REGISTRY_PATH = Path.home() / ".quant-dashboard" / "sources.json"
CORE_FILES = ("state.json", "nav.csv")
OPTIONAL_FILES = ("positions.csv", "orders.csv", "fills.csv", "cash_events.csv")


def normalize_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def is_paper_dir(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.is_dir() and all((candidate / name).is_file() for name in CORE_FILES)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return raw if isinstance(raw, dict) else {}


def find_project_root(data_dir: str | Path) -> Path | None:
    current = normalize_path(data_dir)
    for candidate in (current, *current.parents):
        if (candidate / "config" / "settings.yaml").is_file():
            return candidate
    return None


def _configured_paper_dir(project_root: Path) -> Path | None:
    settings = _read_yaml(project_root / "config" / "settings.yaml")
    paper = settings.get("paper", {}) if isinstance(settings, dict) else {}
    state_dir = paper.get("state_dir") if isinstance(paper, dict) else None
    if not state_dir:
        return None
    candidate = (project_root / str(state_dir)).resolve()
    return candidate if is_paper_dir(candidate) else None


def discover_strategy_dirs(path: str | Path, recursive: bool = False) -> list[Path]:
    """Discover compatible paper directories without modifying them.

    A supplied path may be a paper directory, a quant project root, or a parent
    containing multiple experiments. Recursive mode searches for nav.csv files and
    validates their parent directories with state.json.
    """
    root = normalize_path(path)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在：{root}")
    if not root.is_dir():
        raise NotADirectoryError(f"不是目录：{root}")

    found: set[Path] = set()
    if is_paper_dir(root):
        found.add(root)

    configured = _configured_paper_dir(root) if (root / "config" / "settings.yaml").is_file() else None
    if configured is not None:
        found.add(configured)

    data_root = root / "data"
    if data_root.is_dir():
        for candidate in data_root.glob("paper*"):
            if is_paper_dir(candidate):
                found.add(candidate.resolve())

    if recursive:
        for nav_file in root.rglob("nav.csv"):
            candidate = nav_file.parent
            if is_paper_dir(candidate):
                found.add(candidate.resolve())

    return sorted(found, key=lambda item: str(item).lower())


class SourceRegistry:
    """Small local registry containing paths only; trading data remains untouched."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self.path = path

    def load(self) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        sources = raw.get("sources", []) if isinstance(raw, dict) else []
        clean: list[dict[str, str]] = []
        for item in sources:
            if not isinstance(item, dict) or not item.get("path"):
                continue
            clean.append({"path": str(item["path"]), "label": str(item.get("label", ""))})
        return clean

    def save(self, sources: list[dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"sources": sources}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def add(self, data_dirs: list[Path], label: str = "") -> int:
        sources = self.load()
        existing = {str(normalize_path(item["path"])) for item in sources}
        added = 0
        for data_dir in data_dirs:
            normalized = str(normalize_path(data_dir))
            if normalized in existing:
                continue
            sources.append({"path": normalized, "label": label if len(data_dirs) == 1 else ""})
            existing.add(normalized)
            added += 1
        if added:
            self.save(sources)
        return added

    def remove(self, path: str | Path) -> None:
        target = str(normalize_path(path))
        sources = [item for item in self.load() if str(normalize_path(item["path"])) != target]
        self.save(sources)

    def update_label(self, path: str | Path, label: str) -> None:
        target = str(normalize_path(path))
        sources = self.load()
        for item in sources:
            if str(normalize_path(item["path"])) == target:
                item["label"] = label.strip()
        self.save(sources)
