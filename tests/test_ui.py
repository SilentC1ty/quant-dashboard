import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from test_dashboard import _write_minimal_project

APP = Path(__file__).resolve().parents[1] / "app.py"


def launch(monkeypatch, tmp_path, sources=()):
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"sources": [{"path": str(path), "label": ""} for path in sources]}), encoding="utf-8")
    monkeypatch.setenv("QUANT_DASHBOARD_REGISTRY", str(registry))
    return AppTest.from_file(str(APP), default_timeout=20).run(), registry


@pytest.mark.parametrize("page", ["Overview", "Performance", "Positions", "Trades", "Data Sources"])
def test_every_page_renders_short_sample_without_exceptions(tmp_path, monkeypatch, page):
    path = _write_minimal_project(tmp_path / "quant")
    app, _ = launch(monkeypatch, tmp_path, [path])
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception
    if page == "Overview":
        assert any("365" in caption.value for caption in app.caption)
    if page == "Performance":
        assert any("还需" in message.value for message in app.info)
    if page == "Trades":
        assert any("历史创建状态" in caption.value for caption in app.caption)


def test_registry_create_read_update_remove_and_restore(tmp_path, monkeypatch):
    path = _write_minimal_project(tmp_path / "quant")
    original = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    app, registry = launch(monkeypatch, tmp_path)
    assert app.warning
    app.sidebar.radio[0].set_value("Data Sources").run()
    app.text_input[0].set_value(str(path)).run()
    next(button for button in app.button if button.label == "添加").click().run()
    assert len(json.loads(registry.read_text(encoding="utf-8"))["sources"]) == 1
    next(field for field in app.text_input if field.label == "显示名称").set_value("核验盘").run()
    next(button for button in app.button if button.label == "保存名称").click().run()
    assert json.loads(registry.read_text(encoding="utf-8"))["sources"][0]["label"] == "核验盘"
    next(button for button in app.button if button.label == "移除").click().run()
    assert json.loads(registry.read_text(encoding="utf-8"))["sources"] == []
    app.text_input[0].set_value(str(path)).run()
    next(button for button in app.button if button.label == "添加").click().run()
    assert len(json.loads(registry.read_text(encoding="utf-8"))["sources"]) == 1
    assert not app.exception
    assert {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()} == original


def test_bad_source_error_recovers_after_fix_and_refresh(tmp_path, monkeypatch):
    path = _write_minimal_project(tmp_path / "quant")
    original = (path / "state.json").read_bytes()
    (path / "state.json").write_text("{broken", encoding="utf-8")
    app, _ = launch(monkeypatch, tmp_path, [path])
    assert app.error
    assert not app.exception
    (path / "state.json").write_bytes(original)
    app.button(key="refresh-data").click().run()
    assert not app.error
    assert not app.exception
    assert any(title.value == "Overview" for title in app.title)


def test_invalid_path_and_no_selected_strategy_are_clear_states(tmp_path, monkeypatch):
    path = _write_minimal_project(tmp_path / "quant")
    app, _ = launch(monkeypatch, tmp_path, [path])
    app.sidebar.multiselect[0].set_value([]).run()
    assert any("至少选择" in message.value for message in app.info)
    app.sidebar.radio[0].set_value("Data Sources").run()
    app.text_input[0].set_value(str(tmp_path / "does-not-exist")).run()
    next(button for button in app.button if button.label == "添加").click().run()
    assert app.error
    assert not app.exception


def test_config_edit_invalidates_source_metadata_cache(tmp_path, monkeypatch):
    path = _write_minimal_project(tmp_path / "quant")
    app, _ = launch(monkeypatch, tmp_path, [path])
    assert app.dataframe[0].value["调仓"].iloc[0] == "双周"
    config = path.parent.parent / "config/settings.yaml"
    config.write_text(config.read_text(encoding="utf-8").replace("every: 2", "every: 1"), encoding="utf-8")
    app.run()
    assert app.dataframe[0].value["调仓"].iloc[0] == "每周"
    assert not app.exception
