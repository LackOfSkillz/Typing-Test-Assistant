from __future__ import annotations

import pathlib
import re

CORE = pathlib.Path(__file__).resolve().parents[2] / "typing_assistant" / "core"

FORBIDDEN = (
    "os", "sys", "time", "ctypes", "tkinter", "customtkinter",
    "cv2", "PIL", "pytesseract", "pyautogui", "pynput", "threading", "queue",
)


def _imported_modules(source: str) -> set[str]:
    found = set()
    for line in source.splitlines():
        line = line.strip()
        match = re.match(r"^(?:import|from)\s+([A-Za-z_][\w.]*)", line)
        if match:
            found.add(match.group(1).split(".")[0])
    return found


def test_core_modules_exist():
    assert CORE.is_dir(), f"{CORE} should exist"


def test_core_imports_nothing_impure():
    offenders = {}
    for path in sorted(CORE.glob("*.py")):
        bad = _imported_modules(path.read_text(encoding="utf-8")) & set(FORBIDDEN)
        if bad:
            offenders[path.name] = sorted(bad)
    assert offenders == {}, f"core/ must stay pure, found: {offenders}"


def test_core_does_not_use_global_random():
    offenders = []
    for path in sorted(CORE.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for call in ("random.random(", "random.uniform(", "random.choice(",
                     "random.lognormvariate(", "random.gauss("):
            if call in source:
                offenders.append(f"{path.name}: {call}")
    assert offenders == [], (
        "core/ must take an injected random.Random, not call the module directly: "
        f"{offenders}"
    )
