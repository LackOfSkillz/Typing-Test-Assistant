"""Where the per-machine calibration factor lives.

%APPDATA%\\TypingAssistant\\, not the working directory. The old config was read
from the current directory (``main.py:21``), so running the tool from anywhere
else silently started from defaults.
"""

from __future__ import annotations

import json
import os
import pathlib

_APP_FOLDER = "TypingAssistant"
_FILENAME = "calibration.json"
_SCHEMA_VERSION = 1


def config_dir() -> pathlib.Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return pathlib.Path(base) / _APP_FOLDER


def _path() -> pathlib.Path:
    return config_dir() / _FILENAME


def load_calibration(default: float = 1.0) -> float:
    """Return the stored factor, or *default* if absent or unreadable."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    value = data.get("factor", default)
    try:
        factor = float(value)
    except (TypeError, ValueError):
        return default
    return factor if factor > 0 else default


def save_calibration(factor: float) -> pathlib.Path:
    """Write *factor*, creating the directory if needed. Returns the path."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _path()
    path.write_text(
        json.dumps({"version": _SCHEMA_VERSION, "factor": factor}, indent=2),
        encoding="utf-8",
    )
    return path
