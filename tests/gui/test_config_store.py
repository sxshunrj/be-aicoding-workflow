from __future__ import annotations

from pathlib import Path

from ai_workflow_gui.config_store import (
    GuiConfig,
    RepoEntry,
    load_config,
    repo_id,
    save_config,
)


def test_load_missing_file_returns_empty(tmp_path: Path):
    config = load_config(tmp_path / "none.json")
    assert config == GuiConfig()


def test_load_corrupt_file_returns_empty(tmp_path: Path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_config(path) == GuiConfig()


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "gui" / "config.json"
    config = GuiConfig(
        repos=(RepoEntry(id="abcd1234", name="demo", path="/tmp/demo"),),
        reviewer="sunx",
    )
    save_config(config, path)
    loaded = load_config(path)
    assert loaded == config


def test_repo_id_is_stable_and_pathsensitive(tmp_path: Path):
    first = tmp_path / "repo"
    first.mkdir()
    same = repo_id(first)
    assert repo_id(first) == same
    assert len(same) == 8
    other = tmp_path / "other"
    other.mkdir()
    assert repo_id(other) != same
