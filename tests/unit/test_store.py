from __future__ import annotations

import json

from typing_assistant.adapters import store


def test_config_dir_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert store.config_dir() == tmp_path / "TypingAssistant"


def test_missing_file_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert store.load_calibration(default=1.0) == 1.0


def test_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    store.save_calibration(0.87)
    assert store.load_calibration() == 0.87


def test_saved_file_is_versioned(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = store.save_calibration(0.9)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["factor"] == 0.9


def test_corrupt_file_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text("{not json", encoding="utf-8")
    assert store.load_calibration(default=1.0) == 1.0


def test_nonsense_factor_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text(
        json.dumps({"version": 1, "factor": "banana"}), encoding="utf-8"
    )
    assert store.load_calibration(default=1.0) == 1.0


def test_zero_factor_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text(
        json.dumps({"version": 1, "factor": 0}), encoding="utf-8"
    )
    assert store.load_calibration(default=1.0) == 1.0


def test_non_object_json_returns_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    directory = tmp_path / "TypingAssistant"
    directory.mkdir()
    (directory / "calibration.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert store.load_calibration(default=1.0) == 1.0
