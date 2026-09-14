# Core Modules and Practice Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the measurement harness and the four pure `core/` modules — text normalization, OCR correction, the append-only cursor, and WPM pacing — each fully tested with no screen, keyboard, or wall clock required.

**Architecture:** Everything in this plan is either a self-contained HTML file or a pure Python function over strings, numbers and frozen dataclasses. No Windows APIs, no Tesseract, no Tk. That is deliberate: these modules hold all the accuracy-critical logic, so they must be testable in CI without a display. Adapters that touch the real world come in Plan 2 and consume the interfaces defined here.

**Tech Stack:** Python 3.9+, pytest, Hypothesis. The practice target is dependency-free HTML/CSS/JS served by `python -m http.server`.

**Spec:** [`docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md`](../specs/2026-09-14-typing-assistant-redesign-design.md)

## Global Constraints

- **Python floor: 3.9.** Use `from __future__ import annotations` in every module so builtin generic syntax (`tuple[str, ...]`) is legal on 3.9.
- **`core/` is pure.** No imports from `os`, `time`, `ctypes`, `tkinter`, `cv2`, `PIL`, or `pytesseract`. Randomness only via an injected `random.Random`. A test enforces this (Task 1).
- **Determinism.** Any function using randomness takes an `rng: random.Random` parameter. Never call the `random` module's global functions.
- **Dependencies for this plan: `pytest`, `hypothesis` only.** Do not add `opencv-python-headless` yet; it belongs to Plan 3.
- **Licence: 0BSD.** No copyright headers in source files; the root `LICENSE` covers everything.
- **Spacing default is faithful.** Reproduce source whitespace exactly. Sentence double-spacing is opt-in via `SpacingMode.DOUBLE`. This supersedes spec §6.6, which described conditional double-spacing as the default; inserting a space the source does not contain is itself a scored error.
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `test:`, `chore:`).

---

### Task 1: Test scaffolding, package skeleton, and the purity guard

**Files:**
- Create: `pyproject.toml`
- Create: `typing_assistant/__init__.py`
- Create: `typing_assistant/core/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Test: `tests/unit/test_core_purity.py`
- Create: `.github/workflows/ci.yml`
- Create: `requirements-dev.txt`

**Interfaces:**
- Consumes: nothing.
- Produces: the `typing_assistant.core` package that every later task adds modules to, and a CI job that runs `pytest`.

- [ ] **Step 1: Create the package skeleton**

```bash
mkdir -p typing_assistant/core tests/unit .github/workflows
touch typing_assistant/__init__.py typing_assistant/core/__init__.py
touch tests/__init__.py tests/unit/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "typing-assistant"
version = "2.0.0.dev0"
description = "Assistive typing tool that reads text from the screen and types it for you"
requires-python = ">=3.9"
license = { text = "0BSD" }

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["typing_assistant*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers"
```

- [ ] **Step 3: Write `requirements-dev.txt`**

```
pytest==8.3.3
hypothesis==6.112.1
```

- [ ] **Step 4: Install dev dependencies**

Run: `pip install -r requirements-dev.txt`
Expected: pytest and hypothesis install successfully.

- [ ] **Step 5: Write the failing purity test**

This test is the mechanical enforcement of the Global Constraint that `core/` is pure. It reads the source as text rather than importing it, so it works even before the modules exist.

```python
# tests/unit/test_core_purity.py
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
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/unit/test_core_purity.py -v`
Expected: 3 passed. (`core/` exists and is empty, so there is nothing impure to find yet. This test becomes meaningful as modules land.)

- [ ] **Step 7: Write the CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  test:
    runs-on: windows-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install dev dependencies
        run: pip install -r requirements-dev.txt
      - name: Run tests
        run: pytest
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml requirements-dev.txt typing_assistant tests .github
git commit -m "chore: add package skeleton, pytest scaffolding, and core purity guard"
```

---

### Task 2: Local practice target

A fake typing test. It scrolls a fixed line window and recolors typed text the way typing.com does, and it records every keystroke with a high-resolution timestamp. This is what makes every acceptance criterion in spec §9.6 measurable without spending a live test attempt.

**Files:**
- Create: `tools/practice/index.html`
- Create: `tools/practice/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a page exposing `window.practice` with `{ reset(), stats(), log() }` for automated inspection, and a visible passage element with `id="passage"`. Plan 2's end-to-end tests drive this page.

- [ ] **Step 1: Write the practice target**

```html
<!-- tools/practice/index.html -->
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Practice Typing Test</title>
<style>
  :root { --bg:#fff; --fg:#111; --done:#1a7f37; --bad:#c9252d; --pend:#888; --cur:#0b5fff; }
  body { background:var(--bg); color:var(--fg); font-family:system-ui,sans-serif;
         margin:0; padding:32px; }
  h1 { font-size:18px; font-weight:600; margin:0 0 16px; }
  #frame { border:1px solid #ccc; border-radius:8px; padding:20px 24px;
           max-width:760px; background:#fff; }
  /* A fixed three-line window that scrolls, mirroring typing.com's behaviour. */
  #window { height:calc(3 * 2.2em); overflow:hidden; position:relative; }
  #passage { font-family:Georgia,serif; font-size:22px; line-height:2.2em;
             white-space:pre-wrap; transition:transform .12s linear; }
  .ch { color:var(--pend); }
  .ch.done { color:var(--done); }
  .ch.bad  { color:var(--bad); text-decoration:underline; }
  .ch.cur  { background:var(--cur); color:#fff; border-radius:2px; }
  #stats { margin-top:16px; font-family:ui-monospace,monospace; font-size:14px;
           display:flex; gap:24px; flex-wrap:wrap; }
  #stats b { font-weight:600; }
  #controls { margin-top:16px; display:flex; gap:12px; flex-wrap:wrap; }
  button, select { font-size:15px; padding:10px 16px; min-height:44px; cursor:pointer; }
  #sink { position:absolute; opacity:0; pointer-events:none; }
  .hint { color:#555; font-size:13px; margin-top:12px; max-width:760px; }
</style>
</head>
<body>
<h1>Practice Typing Test <span style="font-weight:400;color:#666">— local harness, no network</span></h1>

<div id="frame">
  <div id="window"><div id="passage"></div></div>
  <div id="stats">
    <span>WPM <b id="s-wpm">0.0</b></span>
    <span>accuracy <b id="s-acc">100.0%</b></span>
    <span>typed <b id="s-typed">0</b>/<b id="s-total">0</b></span>
    <span>errors <b id="s-err">0</b></span>
    <span>elapsed <b id="s-time">0.00</b>s</span>
  </div>
</div>

<div id="controls">
  <select id="passage-pick" aria-label="Passage"></select>
  <button id="btn-reset">Reset</button>
  <button id="btn-copy">Copy keystroke log</button>
</div>

<p class="hint">
  Click the passage then type. Already-typed characters recolor, which is the OCR
  flicker case the append-only cursor must tolerate. Every keystroke is timestamped
  with <code>performance.now()</code>; read it from the console with
  <code>practice.log()</code> or <code>practice.stats()</code>.
</p>

<input id="sink" autocomplete="off" aria-hidden="true" tabindex="-1">

<script>
(function () {
  "use strict";

  var PASSAGES = {
    "plain": "The quick brown fox jumps over the lazy dog. Pack my box with five " +
             "dozen liquor jugs. How vexingly quick daft zebras jump!",
    "punctuation-traps": "Mr. Smith paid 3.14 dollars, e.g. a small sum. See " +
             "https://x.com/a.b for details. Dr. Jones agreed. The total was 1,024 units.",
    "long-scroll": "Accessibility is not a feature that gets added at the end of a " +
             "project. It is a property of decisions made throughout. A tool that " +
             "demands a precise drag gesture has already excluded someone, no matter " +
             "how carefully the rest of it was built. The remedy is rarely more " +
             "settings; it is usually fewer required motions. Consider what the " +
             "smallest possible interaction could be, and then build for that."
  };

  var passageEl = document.getElementById("passage");
  var windowEl = document.getElementById("window");
  var sink = document.getElementById("sink");
  var pick = document.getElementById("passage-pick");

  var target = "";
  var spans = [];
  var pos = 0;
  var errors = 0;
  var startedAt = null;
  var keystrokes = [];
  var lineHeight = 0;

  function render(text) {
    target = text;
    passageEl.textContent = "";
    spans = [];
    for (var i = 0; i < text.length; i++) {
      var s = document.createElement("span");
      s.className = "ch";
      // Render spaces as non-breaking so wrapping does not eat them visually.
      s.textContent = text[i];
      passageEl.appendChild(s);
      spans.push(s);
    }
    lineHeight = parseFloat(getComputedStyle(passageEl).lineHeight) || 48;
    document.getElementById("s-total").textContent = String(text.length);
  }

  function paint() {
    for (var i = 0; i < spans.length; i++) {
      spans[i].classList.remove("cur");
    }
    if (pos < spans.length) spans[pos].classList.add("cur");
    scrollToCursor();
    updateStats();
  }

  // Keep the cursor on the middle line of the three-line window.
  function scrollToCursor() {
    if (!spans.length) return;
    var cursorTop = spans[Math.min(pos, spans.length - 1)].offsetTop;
    var line = Math.round(cursorTop / lineHeight);
    var shift = Math.max(0, line - 1) * lineHeight;
    passageEl.style.transform = "translateY(" + (-shift) + "px)";
  }

  function elapsed() {
    return startedAt === null ? 0 : (performance.now() - startedAt) / 1000;
  }

  function grossWpm() {
    var secs = elapsed();
    if (secs <= 0) return 0;
    return (pos / 5) / (secs / 60);
  }

  function updateStats() {
    document.getElementById("s-wpm").textContent = grossWpm().toFixed(1);
    var acc = pos === 0 ? 100 : ((pos - errors) / pos) * 100;
    document.getElementById("s-acc").textContent = Math.max(0, acc).toFixed(1) + "%";
    document.getElementById("s-typed").textContent = String(pos);
    document.getElementById("s-err").textContent = String(errors);
    document.getElementById("s-time").textContent = elapsed().toFixed(2);
  }

  function reset(name) {
    var key = name || pick.value || "plain";
    pos = 0;
    errors = 0;
    startedAt = null;
    keystrokes = [];
    render(PASSAGES[key] !== undefined ? PASSAGES[key] : PASSAGES.plain);
    paint();
    sink.focus();
  }

  function onChar(ch) {
    if (pos >= target.length) return;
    if (startedAt === null) startedAt = performance.now();
    var expected = target[pos];
    var ok = ch === expected;
    keystrokes.push({ t: performance.now(), ch: ch, expected: expected, ok: ok });
    spans[pos].classList.remove("cur");
    spans[pos].classList.add(ok ? "done" : "bad");
    if (!ok) errors++;
    pos++;
    paint();
  }

  function onBackspace() {
    if (pos === 0) return;
    keystrokes.push({ t: performance.now(), ch: "\b", expected: null, ok: null });
    pos--;
    if (spans[pos].classList.contains("bad")) errors = Math.max(0, errors - 1);
    spans[pos].className = "ch";
    paint();
  }

  document.addEventListener("keydown", function (e) {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key === "Backspace") { e.preventDefault(); onBackspace(); return; }
    if (e.key === "Enter") { e.preventDefault(); onChar("\n"); return; }
    if (e.key.length === 1) { e.preventDefault(); onChar(e.key); }
  });

  document.getElementById("btn-reset").addEventListener("click", function () { reset(); });
  document.getElementById("btn-copy").addEventListener("click", function () {
    var text = JSON.stringify(keystrokes, null, 2);
    if (navigator.clipboard) navigator.clipboard.writeText(text);
    console.log(text);
  });
  pick.addEventListener("change", function () { reset(pick.value); });
  document.getElementById("frame").addEventListener("click", function () { sink.focus(); });

  Object.keys(PASSAGES).forEach(function (k) {
    var o = document.createElement("option");
    o.value = k;
    o.textContent = k;
    pick.appendChild(o);
  });

  // Automation surface, used by Plan 2's end-to-end tests.
  window.practice = {
    reset: reset,
    log: function () { return keystrokes.slice(); },
    stats: function () {
      return {
        wpm: grossWpm(),
        accuracy: pos === 0 ? 100 : ((pos - errors) / pos) * 100,
        typed: pos,
        total: target.length,
        errors: errors,
        elapsed: elapsed(),
        typedText: target.slice(0, pos),
        target: target
      };
    },
    passages: function () { return Object.keys(PASSAGES); }
  };

  reset("plain");
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Write the tools README**

```markdown
<!-- tools/practice/README.md -->
# Practice Target

A local fake typing test for measuring the assistant without spending a real test
attempt.

## Run

    python -m http.server 8777 --directory tools/practice

Then open <http://localhost:8777/>.

## Why it exists

- Unlimited free end-to-end runs.
- Objective measured WPM and accuracy, independent of what the tool reports about itself.
- A timestamped keystroke log, so the pacing engine's rhythm can be compared against a
  recording of real human typing.
- It reproduces the two things that break the old implementation: a scrolling fixed line
  window, and recoloring of already-typed text.

## Automation surface

`window.practice` exposes:

- `reset(name)` — restart with a named passage
- `stats()` — `{ wpm, accuracy, typed, total, errors, elapsed, typedText, target }`
- `log()` — every keystroke as `{ t, ch, expected, ok }`, `t` from `performance.now()`
- `passages()` — available passage names

## Passages

- `plain` — ordinary prose
- `punctuation-traps` — `Mr.`, `3.14`, `e.g.`, a URL. Exercises the sentence-ending
  rule; a naive double-space after every period fails this passage visibly.
- `long-scroll` — long enough to force several scroll steps
```

- [ ] **Step 3: Serve the page**

Run: `python -m http.server 8777 --directory tools/practice`
Expected: server starts and reports `Serving HTTP on :: port 8777`.

- [ ] **Step 4: Verify it in a browser**

Open <http://localhost:8777/>. Check each of these by hand:

1. The passage renders, and the first character has a blue cursor highlight.
2. Typing correct characters turns them green and advances the cursor.
3. Typing a wrong character turns it red and underlined, and `errors` increments.
4. Backspace steps back and clears the mark; an incorrect character's error is retracted.
5. Selecting `long-scroll` and typing past the second line scrolls the window.
6. In the browser console, `practice.stats()` returns a populated object and
   `practice.log()` returns entries with monotonically increasing `t`.

- [ ] **Step 5: Commit**

```bash
git add tools/practice
git commit -m "feat: add local practice target for measuring WPM and accuracy"
```

---

### Task 3: `core/text.py` — normalization

Replaces the destructive `text.split()` at `main.py:178` and the single-pass
`replace('  ', ' ')` at `main.py:123`.

**Files:**
- Create: `typing_assistant/core/text.py`
- Test: `tests/unit/test_text.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `NORMALIZATION_MAP: dict[str, str]`
  - `normalize(raw: str) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_text.py
from __future__ import annotations

import pytest

from typing_assistant.core.text import NORMALIZATION_MAP, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("“hello”", '"hello"'),
        ("‘hi’", "'hi'"),
        ("a—b", "a-b"),
        ("a–b", "a-b"),
        ("wait…", "wait..."),
        ("café", "café"),
        ("a b", "a b"),
    ],
)
def test_unicode_punctuation_is_mapped(raw, expected):
    assert normalize(raw) == expected


def test_runs_of_spaces_collapse_fully():
    # main.py:123 used replace("  ", " "), which turns three spaces into two.
    assert normalize("a   b") == "a b"
    assert normalize("a       b") == "a b"


def test_tabs_become_spaces():
    assert normalize("a\tb") == "a b"


def test_single_newline_is_preserved():
    assert normalize("line one\nline two") == "line one\nline two"


def test_paragraph_break_is_preserved():
    assert normalize("para one\n\npara two") == "para one\n\npara two"


def test_three_or_more_newlines_collapse_to_two():
    assert normalize("a\n\n\n\nb") == "a\n\nb"


def test_crlf_is_normalized():
    assert normalize("a\r\nb") == "a\nb"


def test_trailing_whitespace_per_line_is_stripped():
    assert normalize("a   \nb  ") == "a\nb"


def test_leading_and_trailing_whitespace_is_stripped():
    assert normalize("   hello   ") == "hello"


def test_empty_input():
    assert normalize("") == ""
    assert normalize("   \n  \n ") == ""


def test_normalization_map_values_are_ascii():
    for src, dst in NORMALIZATION_MAP.items():
        assert dst.isascii(), f"{src!r} maps to non-ascii {dst!r}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_text.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'typing_assistant.core.text'`

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/text.py
"""Normalization of OCR output into text a keyboard can reproduce exactly.

Pure module: no I/O, no randomness. See the plan's Global Constraints.
"""

from __future__ import annotations

import re

#: Characters OCR commonly returns that no keyboard key produces directly.
#: Every value must be ASCII so the keyboard adapter can always send it.
NORMALIZATION_MAP = {
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "„": '"',   # low double quote
    "‘": "'",   # left single quote
    "’": "'",   # right single quote / apostrophe
    "‚": "'",   # low single quote
    "′": "'",   # prime
    "″": '"',   # double prime
    "—": "-",   # em dash
    "–": "-",   # en dash
    "−": "-",   # minus sign
    "…": "...",  # ellipsis
    " ": " ",   # non-breaking space
    " ": " ",   # en space
    " ": " ",   # em space
    " ": " ",   # thin space
    "​": "",    # zero-width space
    "﻿": "",    # byte-order mark
}

_TRANSLATION = {ord(src): dst for src, dst in NORMALIZATION_MAP.items()}

_HORIZONTAL_WS = re.compile(r"[ \t\f\v]+")
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)
_LEADING_WS = re.compile(r"^[ \t]+", re.MULTILINE)
_MANY_NEWLINES = re.compile(r"\n{3,}")


def normalize(raw: str) -> str:
    """Return *raw* with unreproducible characters mapped and whitespace tidied.

    Paragraph structure is preserved: a single newline stays a newline, a blank
    line stays a blank line. Runs of three or more newlines collapse to two.
    Horizontal whitespace runs collapse to a single space.
    """
    if not raw:
        return ""

    text = raw.translate(_TRANSLATION)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _TRAILING_WS.sub("", text)
    text = _LEADING_WS.sub("", text)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_text.py tests/unit/test_core_purity.py -v`
Expected: all pass. The purity test now has a real module to inspect.

- [ ] **Step 5: Commit**

```bash
git add typing_assistant/core/text.py tests/unit/test_text.py
git commit -m "feat: add text normalization preserving paragraph structure"
```

---

### Task 4: `core/pacing.py` — sentence detection and the keystroke schedule

Fixes four defects at once: the unconditional double-space (`main.py:190`), spaces
costing no time (`main.py:199`), flat uniform jitter (`main.py:193`), and the magic
`CALIBRATION_FACTOR` (`main.py:172`).

The schedule is **normalized to the target duration**, so total time always equals what
the requested WPM implies. Rhythm shaping redistributes time within that budget rather
than adding to it. This is what makes the WPM setting honest.

**Files:**
- Create: `typing_assistant/core/pacing.py`
- Test: `tests/unit/test_pacing.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CHARS_PER_WORD: int` (= 5)
  - `ABBREVIATIONS: frozenset[str]`
  - `class SpacingMode` with members `FAITHFUL`, `DOUBLE`
  - `@dataclass(frozen=True) PacingConfig(wpm, variation=0.12, word_pause=1.6, sentence_pause=3.0, calibration=1.0, spacing=SpacingMode.FAITHFUL)`
  - `@dataclass(frozen=True) Keystroke(char: str, delay: float)` — `delay` is seconds to wait *before* sending `char`
  - `is_sentence_end(text: str, index: int) -> bool`
  - `apply_spacing(text: str, mode: SpacingMode) -> str`
  - `target_duration(char_count: int, wpm: float) -> float`
  - `measured_wpm(char_count: int, seconds: float) -> float`
  - `schedule(text: str, config: PacingConfig, rng: random.Random) -> tuple[Keystroke, ...]`
  - `total_duration(keystrokes: Sequence[Keystroke]) -> float`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_pacing.py
from __future__ import annotations

import random

import pytest

from typing_assistant.core.pacing import (
    CHARS_PER_WORD,
    Keystroke,
    PacingConfig,
    SpacingMode,
    apply_spacing,
    is_sentence_end,
    measured_wpm,
    schedule,
    target_duration,
    total_duration,
)


# --- sentence-ending detection: the table that main.py:190 fails ---

@pytest.mark.parametrize(
    "text,index,expected",
    [
        ("End. Next", 3, True),          # genuine sentence end
        ("Mr. Smith", 2, False),         # title abbreviation
        ("Dr. Jones", 2, False),
        ("e.g. this", 3, False),         # multi-dot abbreviation
        ("i.e. that", 3, False),
        ("etc. Then", 3, False),
        ("3.14 is pi", 1, False),        # decimal number
        ("https://x.com/a.b end", 16, False),  # inside a URL
        ("a.b@example.com x", 1, False),       # inside an email
        ("Done.", 4, True),              # end of input
        ("word. lower", 4, False),       # next word not capitalised
        ("Wait.  Two", 4, True),         # already double-spaced
    ],
)
def test_is_sentence_end(text, index, expected):
    assert text[index] == ".", "test fixture must point at a period"
    assert is_sentence_end(text, index) is expected


# --- spacing modes ---

def test_faithful_spacing_changes_nothing():
    # The source text is the ground truth; inserting a space it lacks is an error.
    text = "End. Next. Mr. Smith paid 3.14."
    assert apply_spacing(text, SpacingMode.FAITHFUL) == text


def test_double_spacing_only_at_sentence_ends():
    assert apply_spacing("End. Next", SpacingMode.DOUBLE) == "End.  Next"
    assert apply_spacing("Mr. Smith", SpacingMode.DOUBLE) == "Mr. Smith"
    assert apply_spacing("3.14 ok", SpacingMode.DOUBLE) == "3.14 ok"


def test_double_spacing_does_not_stack():
    assert apply_spacing("End.  Next", SpacingMode.DOUBLE) == "End.  Next"


# --- WPM arithmetic ---

def test_target_duration_uses_five_chars_per_word():
    assert CHARS_PER_WORD == 5
    # 300 characters at 60 WPM == 60 words == 60 seconds.
    assert target_duration(300, 60.0) == pytest.approx(60.0)


def test_measured_wpm_is_the_inverse_of_target_duration():
    assert measured_wpm(300, 60.0) == pytest.approx(60.0)
    assert measured_wpm(275, 60.0) == pytest.approx(55.0)


def test_target_duration_rejects_non_positive_wpm():
    with pytest.raises(ValueError):
        target_duration(100, 0)


# --- the schedule ---

def _cfg(**kw):
    base = dict(wpm=55.0)
    base.update(kw)
    return PacingConfig(**base)


def test_schedule_covers_every_character():
    text = "hello world"
    ks = schedule(text, _cfg(), random.Random(1))
    assert "".join(k.char for k in ks) == text


def test_spaces_are_scheduled_keystrokes():
    # main.py:199 pressed space with no sleep, inflating real WPM ~17%.
    ks = schedule("a b", _cfg(), random.Random(1))
    space = [k for k in ks if k.char == " "]
    assert len(space) == 1
    assert space[0].delay > 0


def test_total_duration_matches_the_requested_wpm():
    text = "The quick brown fox jumps over the lazy dog. " * 4
    cfg = _cfg(wpm=55.0)
    ks = schedule(text, cfg, random.Random(7))
    assert total_duration(ks) == pytest.approx(target_duration(len(text), 55.0))


def test_measured_wpm_of_the_schedule_equals_target():
    text = "The quick brown fox jumps over the lazy dog. " * 4
    ks = schedule(text, _cfg(wpm=42.0), random.Random(3))
    got = measured_wpm(len(ks), total_duration(ks))
    assert got == pytest.approx(42.0)


def test_calibration_scales_duration():
    text = "hello world this is a sentence"
    fast = schedule(text, _cfg(calibration=0.5), random.Random(5))
    slow = schedule(text, _cfg(calibration=1.0), random.Random(5))
    assert total_duration(fast) == pytest.approx(total_duration(slow) * 0.5)


def test_schedule_is_deterministic_for_a_seed():
    text = "deterministic output please"
    a = schedule(text, _cfg(), random.Random(99))
    b = schedule(text, _cfg(), random.Random(99))
    assert a == b


def test_different_seeds_give_different_rhythm():
    text = "some text long enough to vary"
    a = schedule(text, _cfg(), random.Random(1))
    b = schedule(text, _cfg(), random.Random(2))
    assert a != b


def test_zero_variation_still_shapes_pauses_but_is_repeatable():
    text = "one two. three"
    a = schedule(text, _cfg(variation=0.0), random.Random(1))
    b = schedule(text, _cfg(variation=0.0), random.Random(2))
    assert a == b, "with no jitter the schedule must not depend on the rng"


def test_word_boundary_pauses_are_longer_than_letters():
    text = "alpha beta gamma delta"
    ks = schedule(text, _cfg(variation=0.0, word_pause=2.0), random.Random(1))
    spaces = [k.delay for k in ks if k.char == " "]
    letters = [k.delay for k in ks if k.char.isalpha()]
    assert min(spaces) > max(letters)


def test_sentence_pause_is_longer_than_word_pause():
    text = "one two. three four"
    ks = schedule(
        text, _cfg(variation=0.0, word_pause=1.5, sentence_pause=4.0), random.Random(1)
    )
    delays = {i: k.delay for i, k in enumerate(ks)}
    space_after_period = next(
        i for i, k in enumerate(ks) if k.char == " " and ks[i - 1].char == "."
    )
    plain_space = next(
        i for i, k in enumerate(ks)
        if k.char == " " and ks[i - 1].char != "." and i != space_after_period
    )
    assert delays[space_after_period] > delays[plain_space]


def test_all_delays_are_positive():
    text = "The quick brown fox. Jumps over! Really? Yes."
    ks = schedule(text, _cfg(), random.Random(11))
    assert all(k.delay > 0 for k in ks)


def test_empty_text_gives_empty_schedule():
    assert schedule("", _cfg(), random.Random(1)) == ()
    assert total_duration(()) == 0.0


def test_keystroke_is_frozen():
    k = Keystroke("a", 0.1)
    with pytest.raises(Exception):
        k.char = "b"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_pacing.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'typing_assistant.core.pacing'`

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/pacing.py
"""Turning text into a timed keystroke schedule.

The schedule is normalized so its total duration is exactly what the requested
WPM implies. Rhythm shaping redistributes time inside that budget; it never adds
to it. This is what lets the WPM setting be honest without a fudge factor.

Pure module: randomness arrives as an injected ``random.Random``.
"""

from __future__ import annotations

import enum
import math
import random
import re
from dataclasses import dataclass, field
from typing import Sequence

#: Standard typing-test definition of a "word": five characters, spaces included.
CHARS_PER_WORD = 5

#: Lowercased, dot-terminated tokens that end in a period without ending a sentence.
ABBREVIATIONS = frozenset(
    {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "rev.", "hon.",
        "vs.", "etc.", "e.g.", "i.e.", "cf.", "al.", "ibid.", "viz.",
        "inc.", "ltd.", "co.", "corp.", "dept.", "univ.",
        "no.", "vol.", "fig.", "ed.", "pp.", "ch.",
        "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.",
        "oct.", "nov.", "dec.",
        "mon.", "tue.", "tues.", "wed.", "thu.", "thurs.", "fri.", "sat.", "sun.",
        "approx.", "est.", "min.", "max.", "avg.", "a.m.", "p.m.",
    }
)

#: Substrings that mark a whitespace-delimited token as a URL, path or address,
#: where an internal period never ends a sentence.
_NON_PROSE_MARKERS = ("://", "/", "@", "\\", "www.")

_SENTENCE_TERMINALS = ".!?"


class SpacingMode(enum.Enum):
    """How to space after a sentence-ending period.

    FAITHFUL reproduces the source exactly and is the default: inserting a space
    the source does not contain is itself a scored error. DOUBLE exists for tests
    that demand typewriter convention.
    """

    FAITHFUL = "faithful"
    DOUBLE = "double"


@dataclass(frozen=True)
class PacingConfig:
    """Parameters controlling the shape and speed of typing."""

    wpm: float
    variation: float = 0.12
    word_pause: float = 1.6
    sentence_pause: float = 3.0
    calibration: float = 1.0
    spacing: SpacingMode = SpacingMode.FAITHFUL

    def __post_init__(self) -> None:
        if self.wpm <= 0:
            raise ValueError("wpm must be positive")
        if self.variation < 0:
            raise ValueError("variation must not be negative")
        if self.calibration <= 0:
            raise ValueError("calibration must be positive")
        if self.word_pause < 1.0 or self.sentence_pause < 1.0:
            raise ValueError("pause factors must be at least 1.0")


@dataclass(frozen=True)
class Keystroke:
    """One character and the delay to wait *before* sending it."""

    char: str
    delay: float


def _token_bounds(text: str, index: int) -> tuple[int, int]:
    """Return the whitespace-delimited token containing *index*."""
    start = index
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    end = index
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def is_sentence_end(text: str, index: int) -> bool:
    """Is the period at *index* the end of a sentence?

    False for abbreviations, decimals, URLs, paths and email addresses, and when
    the following word is not capitalised.
    """
    if index < 0 or index >= len(text) or text[index] != ".":
        return False

    # A digit immediately after means a decimal, e.g. "3.14".
    if index + 1 < len(text) and text[index + 1].isdigit():
        return False

    start, end = _token_bounds(text, index)
    token = text[start:end]
    if any(marker in token for marker in _NON_PROSE_MARKERS):
        return False

    # The token up to and including this period, e.g. "Mr." or "e.g.".
    prefix = text[start : index + 1].lower()
    if prefix in ABBREVIATIONS:
        return False

    # End of input counts as a sentence end.
    rest = text[index + 1 :]
    if not rest.strip():
        return True

    # Otherwise the next non-space character must start a new sentence.
    stripped = rest.lstrip()
    if not rest[:1].isspace():
        return False
    first = stripped[0]
    return first.isupper() or first.isdigit() or first in "\"'"


def apply_spacing(text: str, mode: SpacingMode) -> str:
    """Return *text* with sentence spacing adjusted per *mode*."""
    if mode is SpacingMode.FAITHFUL:
        return text

    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        out.append(ch)
        if ch == "." and is_sentence_end(text, i):
            # Exactly one following space becomes two; leave anything else alone.
            if text[i + 1 : i + 2] == " " and text[i + 2 : i + 3] != " ":
                out.append("  ")
                i += 2
                continue
        i += 1
    return "".join(out)


def target_duration(char_count: int, wpm: float) -> float:
    """Seconds that *char_count* characters should take at *wpm*."""
    if wpm <= 0:
        raise ValueError("wpm must be positive")
    return (char_count / CHARS_PER_WORD) / wpm * 60.0


def measured_wpm(char_count: int, seconds: float) -> float:
    """Gross WPM implied by typing *char_count* characters in *seconds*."""
    if seconds <= 0:
        return 0.0
    return (char_count / CHARS_PER_WORD) / (seconds / 60.0)


def _jitter(rng: random.Random, variation: float) -> float:
    """A positive multiplier with mean ~1 and a right-skewed tail.

    Human inter-key intervals are lognormal-ish: mostly tight, occasionally long.
    A symmetric uniform draw (as in main.py:193) reads as machine-generated.
    """
    if variation <= 0:
        return 1.0
    sigma = variation
    mu = -(sigma ** 2) / 2.0  # so that exp(mu + sigma^2/2) == 1
    return min(3.0, max(0.35, rng.lognormvariate(mu, sigma)))


def _weights(text: str, config: PacingConfig, rng: random.Random) -> list[float]:
    """Relative time weight for each character, before normalization."""
    weights = []
    for i, ch in enumerate(text):
        weight = _jitter(rng, config.variation)
        if ch.isspace():
            previous = text[i - 1] if i > 0 else ""
            if previous == "." and is_sentence_end(text, i - 1):
                weight *= config.sentence_pause
            elif previous in "!?":
                weight *= config.sentence_pause
            else:
                weight *= config.word_pause
        weights.append(weight)
    return weights


def schedule(
    text: str, config: PacingConfig, rng: random.Random
) -> tuple[Keystroke, ...]:
    """Return a keystroke schedule whose total duration matches ``config.wpm``.

    ``config.calibration`` scales the whole schedule to correct for a machine's
    measured deviation; 1.0 means no correction.
    """
    prepared = apply_spacing(text, config.spacing)
    if not prepared:
        return ()

    weights = _weights(prepared, config, rng)
    total_weight = math.fsum(weights)
    budget = target_duration(len(prepared), config.wpm) * config.calibration
    scale = budget / total_weight

    return tuple(
        Keystroke(char=ch, delay=weight * scale)
        for ch, weight in zip(prepared, weights)
    )


def total_duration(keystrokes: Sequence[Keystroke]) -> float:
    """Total scheduled time for *keystrokes*."""
    return math.fsum(k.delay for k in keystrokes)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_pacing.py -v`
Expected: all pass.

- [ ] **Step 5: Run the whole suite**

Run: `pytest`
Expected: all pass, including the purity guard against the new module.

- [ ] **Step 6: Commit**

```bash
git add typing_assistant/core/pacing.py tests/unit/test_pacing.py
git commit -m "feat: add self-normalizing keystroke pacing with honest WPM"
```

---

### Task 5: `core/correction.py` — OCR confidence and repair

Consumes the per-word confidence that `main.py:122` currently discards by calling
`image_to_string` instead of `image_to_data`.

**Files:**
- Create: `typing_assistant/core/correction.py`
- Test: `tests/unit/test_correction.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CONFUSION_PAIRS: tuple[tuple[str, str], ...]`
  - `DEFAULT_THRESHOLD: float` (= 70.0)
  - `@dataclass(frozen=True) Word(text: str, confidence: float)`
  - `@dataclass(frozen=True) Correction(original, corrected, candidates, resolved)`
  - `candidates_for(word: str) -> tuple[str, ...]`
  - `correct_word(word: Word, dictionary, threshold=DEFAULT_THRESHOLD) -> Correction`
  - `correct_words(words, dictionary, threshold=DEFAULT_THRESHOLD) -> tuple[Correction, ...]`
  - `unresolved(corrections) -> tuple[int, ...]`
  - `render(corrections) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_correction.py
from __future__ import annotations

import pytest

from typing_assistant.core.correction import (
    DEFAULT_THRESHOLD,
    Correction,
    Word,
    candidates_for,
    correct_word,
    correct_words,
    render,
    unresolved,
)

DICT = frozenset({"modern", "warning", "hello", "world", "instance", "dinner", "climb"})


# --- candidate generation ---

def test_candidates_include_the_original():
    assert "modem" in candidates_for("modem")


def test_rn_to_m_confusion():
    assert "modern" in candidates_for("modem")


def test_m_to_rn_confusion():
    assert "modem" in candidates_for("modern")


def test_l_one_i_confusion():
    cands = candidates_for("c1imb")
    assert "climb" in cands


def test_zero_o_confusion():
    assert "world" in candidates_for("w0rld")


def test_cl_d_confusion():
    assert "dinner" in candidates_for("clinner")


def test_candidates_are_unique():
    cands = candidates_for("aaa")
    assert len(cands) == len(set(cands))


def test_candidate_generation_is_bounded():
    # Guard against combinatorial explosion on a long token.
    assert len(candidates_for("rnrnrnrnrnrnrnrn")) <= 256


# --- high confidence must never be touched ---

def test_high_confidence_word_passes_through_untouched():
    word = Word("Kowalczyk", 97.0)
    result = correct_word(word, DICT)
    assert result.corrected == "Kowalczyk"
    assert result.resolved is True


def test_high_confidence_word_not_in_dictionary_is_still_kept():
    # A proper noun must not be "fixed" into something in the dictionary.
    result = correct_word(Word("modem", 99.0), DICT)
    assert result.corrected == "modem"
    assert result.resolved is True


# --- low confidence repair ---

def test_low_confidence_word_in_dictionary_is_kept():
    result = correct_word(Word("hello", 20.0), DICT)
    assert result.corrected == "hello"
    assert result.resolved is True


def test_low_confidence_word_with_one_dictionary_candidate_is_corrected():
    result = correct_word(Word("modem", 30.0), DICT)
    assert result.corrected == "modern"
    assert result.resolved is True


def test_low_confidence_word_with_no_candidate_is_unresolved():
    result = correct_word(Word("zzqqx", 10.0), DICT)
    assert result.resolved is False
    assert result.corrected == "zzqqx"
    assert "zzqqx" in result.candidates


def test_unresolved_word_offers_candidates_for_the_prompt():
    result = correct_word(Word("w0rld", 10.0), frozenset({"world", "would"}))
    assert result.resolved is True
    assert result.corrected == "world"


def test_ambiguous_candidates_are_unresolved_with_all_options():
    # Both "dinner" and "clinner" plausible -> ask rather than guess.
    result = correct_word(Word("clinner", 15.0), frozenset({"dinner", "clinner"}))
    assert result.resolved is False
    assert set(result.candidates) >= {"dinner", "clinner"}


# --- punctuation and casing are preserved ---

def test_trailing_punctuation_is_preserved_through_correction():
    result = correct_word(Word("modem.", 30.0), DICT)
    assert result.corrected == "modern."


def test_leading_punctuation_is_preserved():
    result = correct_word(Word('"modem', 30.0), DICT)
    assert result.corrected == '"modern'


def test_capitalisation_is_preserved():
    result = correct_word(Word("Modem", 30.0), DICT)
    assert result.corrected == "Modern"


def test_pure_punctuation_token_is_left_alone():
    result = correct_word(Word("--", 5.0), DICT)
    assert result.corrected == "--"
    assert result.resolved is True


def test_numeric_token_is_never_corrected():
    # "1024" must not become "l024" via the l/1 confusion pair.
    result = correct_word(Word("1024", 20.0), DICT)
    assert result.corrected == "1024"
    assert result.resolved is True


# --- sequences ---

def test_correct_words_returns_one_correction_per_word():
    words = [Word("hello", 95.0), Word("modem", 20.0)]
    results = correct_words(words, DICT)
    assert len(results) == 2
    assert results[1].corrected == "modern"


def test_unresolved_reports_indices():
    words = [Word("hello", 95.0), Word("zzqqx", 5.0), Word("world", 95.0)]
    results = correct_words(words, DICT)
    assert unresolved(results) == (1,)


def test_render_joins_with_single_spaces():
    words = [Word("hello", 95.0), Word("modem", 20.0)]
    assert render(correct_words(words, DICT)) == "hello modern"


def test_threshold_default():
    assert DEFAULT_THRESHOLD == 70.0


def test_empty_sequence():
    assert correct_words([], DICT) == ()
    assert render(()) == ""


def test_correction_is_frozen():
    c = Correction("a", "a", ("a",), True)
    with pytest.raises(Exception):
        c.corrected = "b"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_correction.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'typing_assistant.core.correction'`

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/correction.py
"""Repairing low-confidence OCR words without corrupting correct ones.

The dictionary is a source of suggestions, never an authority. A word OCR read
confidently is returned unchanged even when the dictionary does not contain it,
because proper nouns are common and a wrong "fix" is worse than the original.

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

import itertools
import string
from dataclasses import dataclass
from typing import Container, Iterable, Sequence

#: Confidence below which a word is a candidate for repair. Tesseract reports 0-100.
DEFAULT_THRESHOLD = 70.0

#: Bidirectional substitutions Tesseract actually makes on screen-resolution text.
CONFUSION_PAIRS = (
    ("rn", "m"),
    ("m", "rn"),
    ("cl", "d"),
    ("d", "cl"),
    ("l", "1"),
    ("1", "l"),
    ("l", "I"),
    ("I", "l"),
    ("1", "I"),
    ("I", "1"),
    ("0", "O"),
    ("O", "0"),
    ("vv", "w"),
    ("w", "vv"),
)

#: Hard ceiling on generated candidates, so a pathological token cannot explode.
_MAX_CANDIDATES = 256

_PUNCTUATION = set(string.punctuation) | {"—", "–"}


@dataclass(frozen=True)
class Word:
    """One OCR word with the confidence the engine reported for it."""

    text: str
    confidence: float


@dataclass(frozen=True)
class Correction:
    """The outcome of considering one word.

    ``resolved`` is True when the result can be used without asking the user.
    ``candidates`` is what to offer them when it is False.
    """

    original: str
    corrected: str
    candidates: tuple[str, ...]
    resolved: bool


def _split_affixes(token: str) -> tuple[str, str, str]:
    """Split *token* into leading punctuation, core, trailing punctuation."""
    start = 0
    while start < len(token) and token[start] in _PUNCTUATION:
        start += 1
    end = len(token)
    while end > start and token[end - 1] in _PUNCTUATION:
        end -= 1
    return token[:start], token[start:end], token[end:]


def candidates_for(word: str) -> tuple[str, ...]:
    """Return *word* plus plausible confusion-pair variants, original first."""
    seen = [word]
    known = {word}

    # One substitution at a time, applied at every occurrence individually.
    frontier = [word]
    for _ in range(2):  # two passes catches e.g. "rn" plus a digit confusion
        next_frontier = []
        for current in frontier:
            for src, dst in CONFUSION_PAIRS:
                start = 0
                while True:
                    at = current.find(src, start)
                    if at < 0:
                        break
                    variant = current[:at] + dst + current[at + len(src) :]
                    if variant not in known:
                        known.add(variant)
                        seen.append(variant)
                        next_frontier.append(variant)
                        if len(seen) >= _MAX_CANDIDATES:
                            return tuple(seen)
                    start = at + 1
        frontier = next_frontier
        if not frontier:
            break
    return tuple(seen)


def _match_case(source: str, target: str) -> str:
    """Give *target* the capitalisation pattern of *source*."""
    if source.isupper() and len(source) > 1:
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def correct_word(
    word: Word,
    dictionary: Container[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> Correction:
    """Consider one OCR word and decide whether to repair, keep, or ask."""
    original = word.text

    def keep() -> Correction:
        return Correction(original, original, (original,), True)

    if word.confidence >= threshold:
        return keep()

    leading, core, trailing = _split_affixes(original)
    if not core:
        return keep()  # pure punctuation
    if any(ch.isdigit() for ch in core):
        return keep()  # never rewrite numbers

    if core.lower() in dictionary:
        return keep()

    hits = []
    for candidate in candidates_for(core):
        if candidate.lower() in dictionary and candidate not in hits:
            hits.append(candidate)

    if len(hits) == 1:
        fixed = leading + _match_case(core, hits[0]) + trailing
        return Correction(original, fixed, (fixed, original), True)

    if not hits:
        return Correction(original, original, (original,), False)

    options = tuple(
        leading + _match_case(core, hit) + trailing for hit in hits
    ) + (original,)
    return Correction(original, original, options, False)


def correct_words(
    words: Iterable[Word],
    dictionary: Container[str],
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[Correction, ...]:
    """Apply :func:`correct_word` across a sequence."""
    return tuple(correct_word(w, dictionary, threshold) for w in words)


def unresolved(corrections: Sequence[Correction]) -> tuple[int, ...]:
    """Indices of corrections that still need a human decision."""
    return tuple(i for i, c in enumerate(corrections) if not c.resolved)


def render(corrections: Sequence[Correction]) -> str:
    """Join corrected words into a single space-separated string."""
    return " ".join(c.corrected for c in corrections)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_correction.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add typing_assistant/core/correction.py tests/unit/test_correction.py
git commit -m "feat: add confidence-gated OCR correction that never rewrites confident words"
```

---

### Task 6: `core/cursor.py` — the append-only cursor

The structural fix for the worst defect in the old code: the `difflib` filter at
`main.py:151` accepts `replace` opcodes and therefore re-emits words, so one OCR
flicker duplicates text mid-test. typing.com recolors typed words, which makes that
flicker routine.

**Files:**
- Create: `typing_assistant/core/cursor.py`
- Test: `tests/unit/test_cursor.py`
- Test: `tests/unit/test_cursor_properties.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class TypedCursor` with:
    - `known: str` — the whole passage learned so far
    - `emitted: str` — every character actually sent
    - `pending: str` — known text not yet sent
    - `observe(read: str) -> int` — merge an OCR read, returns characters gained
    - `take(count: int) -> str` — mark up to `count` pending characters as emitted
    - `advance_matched(keystrokes: str) -> int` — credit human keystrokes on resume
    - `reset() -> None`

- [ ] **Step 1: Write the failing example tests**

```python
# tests/unit/test_cursor.py
from __future__ import annotations

import pytest

from typing_assistant.core.cursor import TypedCursor


def test_starts_empty():
    c = TypedCursor()
    assert c.known == ""
    assert c.emitted == ""
    assert c.pending == ""


def test_first_observation_becomes_the_passage():
    c = TypedCursor()
    gained = c.observe("hello world")
    assert gained == 11
    assert c.known == "hello world"
    assert c.pending == "hello world"


def test_take_moves_text_from_pending_to_emitted():
    c = TypedCursor()
    c.observe("hello world")
    assert c.take(5) == "hello"
    assert c.emitted == "hello"
    assert c.pending == " world"


def test_take_more_than_pending_returns_what_exists():
    c = TypedCursor()
    c.observe("abc")
    assert c.take(99) == "abc"
    assert c.pending == ""


def test_take_zero_or_negative_is_a_noop():
    c = TypedCursor()
    c.observe("abc")
    assert c.take(0) == ""
    assert c.take(-3) == ""
    assert c.emitted == ""


def test_repeated_identical_read_gains_nothing():
    c = TypedCursor()
    c.observe("hello world")
    assert c.observe("hello world") == 0
    assert c.known == "hello world"


def test_extension_by_prefix_growth():
    c = TypedCursor()
    c.observe("the quick brown")
    gained = c.observe("the quick brown fox jumps")
    assert gained == 10
    assert c.known == "the quick brown fox jumps"


def test_scrolled_read_overlapping_the_tail_extends():
    # The window scrolled: the new read starts mid-passage.
    c = TypedCursor()
    c.observe("alpha beta gamma")
    gained = c.observe("beta gamma delta")
    assert gained == 6
    assert c.known == "alpha beta gamma delta"


def test_truncated_read_is_discarded():
    c = TypedCursor()
    c.observe("alpha beta gamma")
    assert c.observe("alpha beta") == 0
    assert c.known == "alpha beta gamma"


def test_read_contradicting_emitted_text_is_discarded():
    # This is the retype bug. OCR flickers on already-typed text; ignore it.
    c = TypedCursor()
    c.observe("alpha beta gamma")
    c.take(10)  # emitted "alpha beta"
    assert c.observe("alpha bela gamma delta") == 0
    assert c.emitted == "alpha beta"
    assert "bela" not in c.known


def test_unrelated_read_is_discarded():
    c = TypedCursor()
    c.observe("alpha beta")
    assert c.observe("completely different text") == 0
    assert c.known == "alpha beta"


def test_emitted_never_shrinks_across_observations():
    c = TypedCursor()
    c.observe("one two three")
    c.take(7)
    before = c.emitted
    for read in ("one two", "xxx", "", "one two three four"):
        c.observe(read)
        assert c.emitted == before


def test_empty_read_is_a_noop():
    c = TypedCursor()
    c.observe("abc")
    assert c.observe("") == 0


def test_advance_matched_credits_human_keystrokes():
    c = TypedCursor()
    c.observe("hello world")
    c.take(6)  # emitted "hello "
    matched = c.advance_matched("wor")
    assert matched == 3
    assert c.emitted == "hello wor"
    assert c.pending == "ld"


def test_advance_matched_stops_at_the_first_mismatch():
    c = TypedCursor()
    c.observe("hello world")
    c.take(6)
    assert c.advance_matched("wXr") == 1
    assert c.emitted == "hello w"


def test_advance_matched_with_no_match_changes_nothing():
    c = TypedCursor()
    c.observe("hello")
    assert c.advance_matched("zzz") == 0
    assert c.emitted == ""


def test_reset_clears_everything():
    c = TypedCursor()
    c.observe("abc")
    c.take(2)
    c.reset()
    assert (c.known, c.emitted, c.pending) == ("", "", "")


def test_known_always_starts_with_emitted():
    c = TypedCursor()
    for read in ("alpha beta", "beta gamma", "gamma delta epsilon"):
        c.observe(read)
        c.take(4)
        assert c.known.startswith(c.emitted)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cursor.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'typing_assistant.core.cursor'`

- [ ] **Step 3: Write the implementation**

```python
# typing_assistant/core/cursor.py
"""The append-only typed cursor.

Holds the authoritative record of every character actually sent. New OCR reads
may only *extend* what is known; a read that contradicts or merely repeats
already-known text is discarded as noise. That makes duplicate typing impossible
by construction rather than unlikely, replacing the difflib ``replace`` filter at
``main.py:151``.

Pure module: no I/O, no randomness.
"""

from __future__ import annotations

#: Minimum overlap, in characters, before a scrolled read is trusted to join on.
_MIN_OVERLAP = 8


class TypedCursor:
    """Tracks the passage learned so far and how much of it has been emitted."""

    def __init__(self) -> None:
        self._known = ""
        self._emitted = 0

    # --- state ---

    @property
    def known(self) -> str:
        """Every character of the passage learned so far."""
        return self._known

    @property
    def emitted(self) -> str:
        """Every character actually sent. This string only ever grows."""
        return self._known[: self._emitted]

    @property
    def pending(self) -> str:
        """Known text not yet sent."""
        return self._known[self._emitted :]

    def reset(self) -> None:
        """Forget everything. Used when a new run is armed."""
        self._known = ""
        self._emitted = 0

    # --- learning ---

    def observe(self, read: str) -> int:
        """Merge an OCR *read* into the passage; return characters gained.

        Returns 0 and changes nothing unless *read* genuinely extends what is
        already known.
        """
        if not read:
            return 0

        if not self._known:
            self._known = read
            return len(read)

        # Growth at the front: the read is the same passage, seen further along.
        if read.startswith(self._known):
            gained = len(read) - len(self._known)
            self._known = read
            return gained

        # The read is a prefix of, or equal to, what we know: nothing new.
        if self._known.startswith(read):
            return 0

        # Scrolled window: the read's head overlaps our tail. Find the longest
        # such overlap and append only the remainder.
        limit = min(len(read), len(self._known))
        for size in range(limit, _MIN_OVERLAP - 1, -1):
            if self._known.endswith(read[:size]):
                remainder = read[size:]
                if not remainder:
                    return 0
                self._known += remainder
                return len(remainder)

        # No trustworthy relationship. Discard rather than guess; guessing is
        # what produces duplicate typing.
        return 0

    # --- emitting ---

    def take(self, count: int) -> str:
        """Mark up to *count* pending characters as emitted and return them."""
        if count <= 0:
            return ""
        chunk = self._known[self._emitted : self._emitted + count]
        self._emitted += len(chunk)
        return chunk

    def advance_matched(self, keystrokes: str) -> int:
        """Credit *keystrokes* typed by the user, stopping at the first mismatch.

        Used on resume: while paused, the keyboard hook observes what the user
        typed during manual catch-up, so the cursor can advance without re-OCR.
        """
        matched = 0
        for ch in keystrokes:
            if self._emitted + matched >= len(self._known):
                break
            if self._known[self._emitted + matched] != ch:
                break
            matched += 1
        self._emitted += matched
        return matched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cursor.py -v`
Expected: all pass.

- [ ] **Step 5: Write the property tests**

This is the machine-checked form of the invariant. Spec §9.2.

```python
# tests/unit/test_cursor_properties.py
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from typing_assistant.core.cursor import TypedCursor

# Small alphabet so Hypothesis generates overlapping, adversarial reads often.
text = st.text(alphabet="abc ", min_size=0, max_size=40)
reads = st.lists(text, min_size=0, max_size=12)
takes = st.lists(st.integers(min_value=-2, max_value=8), min_size=0, max_size=12)


def _interleave(cursor, read_list, take_list):
    """Apply reads and takes in an interleaved order, collecting emitted chunks."""
    chunks = []
    for i in range(max(len(read_list), len(take_list))):
        if i < len(read_list):
            cursor.observe(read_list[i])
        if i < len(take_list):
            chunks.append(cursor.take(take_list[i]))
    return chunks


@given(reads, takes)
@settings(max_examples=500)
def test_emitted_is_always_a_prefix_of_known(read_list, take_list):
    c = TypedCursor()
    _interleave(c, read_list, take_list)
    assert c.known.startswith(c.emitted)


@given(reads, takes)
@settings(max_examples=500)
def test_emitted_never_shrinks_or_changes(read_list, take_list):
    """The core invariant: emitted only ever grows by appending."""
    c = TypedCursor()
    history = [c.emitted]
    for i in range(max(len(read_list), len(take_list))):
        if i < len(read_list):
            c.observe(read_list[i])
            history.append(c.emitted)
        if i < len(take_list):
            c.take(take_list[i])
            history.append(c.emitted)
    for earlier, later in zip(history, history[1:]):
        assert later.startswith(earlier), (
            f"emitted changed from {earlier!r} to {later!r}"
        )


@given(reads, takes)
@settings(max_examples=500)
def test_concatenated_takes_equal_emitted(read_list, take_list):
    """No character is ever emitted twice, and none is skipped."""
    c = TypedCursor()
    chunks = _interleave(c, read_list, take_list)
    assert "".join(chunks) == c.emitted


@given(reads)
@settings(max_examples=500)
def test_observe_never_shortens_known(read_list):
    c = TypedCursor()
    length = 0
    for read in read_list:
        c.observe(read)
        assert len(c.known) >= length
        length = len(c.known)


@given(text, reads)
@settings(max_examples=500)
def test_fully_emitted_passage_is_never_re_emitted(first, read_list):
    """Emit everything, then feed noise; nothing further may be emitted."""
    c = TypedCursor()
    c.observe(first)
    c.take(len(first))
    emitted_before = c.emitted
    for read in read_list:
        c.observe(read)
    # Anything gained must be genuinely new, never a repeat of the prefix.
    assert c.emitted == emitted_before
    assert c.known.startswith(emitted_before)
```

- [ ] **Step 6: Run the property tests**

Run: `pytest tests/unit/test_cursor_properties.py -v`
Expected: all pass, 500 examples each.

- [ ] **Step 7: Run the whole suite**

Run: `pytest`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add typing_assistant/core/cursor.py tests/unit/test_cursor.py tests/unit/test_cursor_properties.py
git commit -m "feat: add append-only cursor making duplicate typing structurally impossible"
```

---

## Self-review

**Spec coverage for this plan's scope:**

| Spec section | Task |
|---|---|
| §5 `core/` structure, purity boundary | 1 |
| §6.3 normalization, structure preservation | 3 |
| §6.4 correction, confidence gate, must-not-corrupt | 5 |
| §6.5 append-only cursor | 6 |
| §6.6 pacing, jitter shape, sentence spacing, spaces as keystrokes | 4 |
| §6.7 calibration factor consumed by the schedule | 4 (`PacingConfig.calibration`) |
| §6.9 resume via observed keystrokes | 6 (`advance_matched`) |
| §9.1 unit tests, punctuation case table | 3, 4, 5 |
| §9.2 property tests for the cursor invariant | 6 |
| §9.5 practice target | 2 |
| §9.7 CI on windows-latest | 1 |

Deferred by design, with the plan that covers them:

- §6.1 capture, §6.2 OCR, §6.8 keystroke output, §5.1 threading, §5.2 state machine,
  §5.3 abort and pause — **Plan 2**.
- §7 profiles, auto-detect, region editor, wizard, §9.3 golden images, §11 packaging —
  **Plan 3**.
- §9.4 fake adapters — **Plan 2**, since there are no adapters to fake yet.
- §9.6 acceptance criteria — measurable once Plan 2 lands; the harness they need exists
  after Task 2.

**Type consistency check:** `Word` and `Correction` field names are used identically in
Task 5's tests and implementation. `PacingConfig` field names (`wpm`, `variation`,
`word_pause`, `sentence_pause`, `calibration`, `spacing`) match between the interface
block, the tests and the implementation. `TypedCursor`'s members (`known`, `emitted`,
`pending`, `observe`, `take`, `advance_matched`, `reset`) match across the interface
block, both test files and the implementation. `schedule` returns
`tuple[Keystroke, ...]` everywhere.

**Placeholder scan:** none. Every code step contains complete, runnable content.
