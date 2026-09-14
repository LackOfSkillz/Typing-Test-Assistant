# Typing Test Assistant — Redesign

**Date:** 2026-09-14
**Status:** Approved design, pending implementation plan
**Branch:** `redesign/testable-core`

## 1. Context

The current tool is a single 286-line `main.py` written in early 2025. It captures a
screen region, OCRs it, and types the recognized text with humanized timing, then
re-OCRs that region on a 1.5 s loop and diffs to append newly revealed text as the
passage scrolls.

It works, and the incremental-diff idea is sound. But the logic for OCR, threading,
pacing, keyboard I/O and UI is interleaved in one class, so nothing can be tested
without a live screen and a real keyboard. Several defects are latent as a direct
result, including one that can type duplicate text into the target field mid-test.

The tool is an assistive input device for people with limited manual dexterity, and
that constraint is the actual specification: **sustained fine-motor
gestures and timed interactions are defects, not conveniences.** The current tool fails
this on two counts — it requires a click-and-drag to select a region, and it requires a
precise click into a target field inside a fixed, uncancellable 8-second window.

Reference target for all testing: <https://www.typing.com/student/tests>.

## 2. Goals

1. No sustained fine-motor gesture is ever required. No dragging, anywhere.
2. No timed interaction. Nothing the user must complete inside a countdown.
3. A panic stop that works *while typing*, within one keystroke.
4. The WPM setting means what it says, on any machine.
5. Duplicate typing is structurally impossible, not merely unlikely.
6. OCR errors are corrected automatically, and surface for a decision only when genuinely ambiguous.
7. The accuracy-critical logic is unit-testable with no screen and no keyboard.

## 3. Non-goals

- Reading text via accessibility APIs or a browser extension. OCR-only was chosen
  deliberately: it works on proctored desktop applications and locked-down environments,
  and it does not break when a browser changes its internals.
- Screen-reader support. CustomTkinter draws widgets on a canvas and cannot deliver it,
  and it is not a need of the primary user. The UI sits behind a thin boundary so a
  native accessible toolkit can replace it later without touching the core.
- Cross-platform support. Windows-only, as today.
- Simulated typing mistakes. Removed entirely — see section 5.3.
- A general-purpose assistive typer. Scope is typing tests.

## 4. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Product scope | Typing-test tool | Every feature serves one workflow well |
| Text capture | OCR only, done properly | Universal; works where nothing else does; no external fragility |
| Region designation | Saved profiles + auto-detect | Eliminates the drag after first setup; keyboard-only fallback |
| OCR uncertainty | Auto-correct, prompt only on low confidence | Near-zero clock cost in the common case |
| Typing engine | Target WPM, self-calibrating, closed-loop | The setting becomes honest |
| Passage tracking | Append-only cursor | Makes retyping impossible by construction |
| Licence | 0BSD (Zero-Clause BSD) | Most permissive workable option; keeps the liability disclaimer |
| Engineering approach | Restructure into a package around a testable core, same stack | Keeps Python/Tesseract/CustomTkinter; buys regression safety |

## 5. Architecture

```
typing_assistant/
  core/                 pure logic, no I/O, fully unit-tested
    text.py             Unicode normalization, structure preservation
    correction.py       dictionary + confusion-pair repair, confidence scoring
    cursor.py           append-only typed-cursor (the anti-retype invariant)
    pacing.py           WPM to keystroke schedule, closed-loop correction
    profiles.py         profile and config models, schema migration
  adapters/             thin, mockable edges
    capture.py          DPI-correct, multi-monitor screen grab
    ocr.py              Tesseract pipeline: upscale, binarize, per-word confidence
    keyboard.py         SendInput backend, tagged output, abort
    hotkeys.py          low-level keyboard hook, injected-vs-human discrimination
    clock.py            high-resolution waitable timer
  ui/                   CustomTkinter, behind a thin boundary
    indicator.py        always-on-top click-through status pill
    region_editor.py    auto-detect proposal, keyboard nudge, live OCR preview
    settings.py         profiles, target WPM
    resolve.py          one-at-a-time low-confidence prompt
    wizard.py           first-run: find Tesseract, calibrate, first profile
  app.py                state machine, worker thread, queue
tests/
  unit/                 core/ tests, incl. Hypothesis property tests
  golden/               committed PNG fixtures and expected text
  fixtures/             fake adapters: FakeKeyboard, FakeCapture, FakeClock
tools/practice/         local HTML practice target (see section 9.5)
```

The dividing line is that `core/` is functions over strings, numbers and dataclasses.
It never touches a screen, a keyboard or a wall clock. Everything that does is an
adapter behind a small interface, with a fake counterpart in `tests/fixtures/`.

### 5.1 Threading

The Tk thread owns only the UI. One worker thread owns the whole capture-to-type
pipeline. They communicate over a `queue.Queue`.

Configuration is read once into an immutable snapshot when a run is armed, so a run's
behavior cannot change underneath it. Today `start_typing` reloads config from disk
inside the typing path (`main.py:164`) and the check-then-set on `is_typing_event`
(`main.py:160`) is not atomic.

### 5.2 State machine

```
IDLE --arm--> CAPTURING --> [RESOLVING] --> READY --go--> TYPING <=> PAUSED
  ^                                           |              |
  +---------------- abort (any state) --------+--------------+
```

`RESOLVING` is entered only when words remain below the confidence threshold after
correction. The common path is CAPTURING to READY with no interruption.

`READY` waits **indefinitely**. The indicator reads "ready — press <hotkey> to start".
The user clicks into the target field with as much time as needed, then fires the
hotkey one-handed. This replaces the fixed `time.sleep(8)` at `main.py:95`.

### 5.3 Abort and pause

Validated by spike (section 8). Every keystroke the tool emits is stamped with a
signature in `SendInput`'s `dwExtraInfo`. A `WH_KEYBOARD_LL` hook reads that stamp back,
and Windows independently sets `LLKHF_INJECTED` on synthetic events. The rule is
therefore **injected AND carrying our signature = ours; anything else = human hands.**
Two independent discriminators, so another automation tool's output cannot be mistaken
for ours.

- **Human keypress produces an immediate pause.** One mechanism serves as panic stop,
  "let me take over", and resync trigger. This is the behavior the existing user guide
  documents and the code never implemented.
- **A dedicated abort hotkey produces a full stop** to `IDLE`.
- The abort flag is checked between every keystroke. Worst-case stop latency is one
  character, about 20 ms at 55 WPM. Today, once typing starts, `on_activation_hotkey`
  returns early (`main.py:64`) and nothing short of killing the process stops it.

Simulated typing mistakes (`main.py:181`) are removed. Most typing tests score
keystrokes, so typing a wrong character and backspacing it lowers the real score. It
is also the only part of the tool that was pretending; removing it makes the output
straightforwardly "this text, entered accurately, by an assistive device".

### 5.4 Data flow

```
profile region -> DPI-correct grab -> OCR (per-word confidence)
  -> normalize -> correct -> confidence gate -> passage buffer
  -> append-only cursor -> pacing schedule -> SendInput
                               ^
        re-OCR source ---------+   (may only ever extend the buffer)
```

The re-OCR arrow is the only feedback path, and `cursor.py` enforces that it can only
extend the buffer.

## 6. Key algorithms

### 6.1 Capture (`adapters/capture.py`)

Declare per-monitor DPI awareness at process start, then work in physical pixels
throughout. This fixes wrong-region capture on scaled displays, where Tk coordinates
and `ImageGrab` coordinates currently disagree.

Region bounds are clamped against the virtual desktop rectangle
(`SM_XVIRTUALSCREEN`, `SM_YVIRTUALSCREEN`, `SM_CXVIRTUALSCREEN`, `SM_CYVIRTUALSCREEN`),
not `winfo_screenwidth()` / `winfo_screenheight()` as at `main.py:83`, which report the
primary monitor only and crop any second-monitor region.

### 6.2 OCR (`adapters/ocr.py`)

1. Upscale 3-4x. Tesseract is trained near 300 DPI; screen text is about 96 DPI.
2. Adaptive threshold to clean black-on-white.
3. Recognize with `image_to_data`, not `image_to_string`, to obtain **per-word
   confidence**. The current code discards this information, which is what makes a
   confidence gate impossible today.
4. `--oem 3 --psm 6` is retained as appropriate for a uniform text block.

### 6.3 Normalization (`core/text.py`)

Replaces the destructive `text.split()` at `main.py:178`.

- Unicode-normalize smart quotes, em and en dashes, and ellipses to keyboard-sendable
  forms.
- Preserve paragraph structure rather than flattening all newlines.
- Collapse whitespace runs with a regex. `replace('  ', ' ')` at `main.py:123` only
  collapses once, turning three spaces into two.

### 6.4 Correction (`core/correction.py`)

Two passes, applied **only to words below the confidence threshold**:

1. Dictionary lookup.
2. Confusion-pair repair for the substitutions Tesseract actually makes on screen text:
   `rn`/`m`, `l`/`1`/`I`, `0`/`O`, `cl`/`d`.

The dictionary is a suggestion source, not an authority. Proper nouns and deliberate
oddities must pass through unchanged; a correction that corrupts correct text is worse
than the OCR error it replaces. Words still below threshold after both passes go to
`ui/resolve.py`, one at a time, best guess preselected, Enter to accept.

### 6.5 The append-only cursor (`core/cursor.py`)

Holds the authoritative record of every character actually emitted. New OCR reads may
only extend it. Any read that matches or contradicts already-emitted text is discarded
as OCR noise.

This replaces the `difflib` filter at `main.py:151`, which accepts both `insert` and
**`replace`** opcodes and therefore re-emits words. A single OCR flicker on
already-typed text causes duplicate output mid-test. typing.com recolors words as they
are typed, which changes their pixels and makes exactly that flicker routine.

The invariant is machine-checked by property tests (section 9.2).

### 6.6 Pacing (`core/pacing.py`)

Pure: takes text and a target WPM, returns a schedule of `(char, delay)` pairs.

Two existing bugs explain the magic constant. Spaces are free in the current loop —
`main.py:199` presses space with no sleep while every other character gets one — so for
five-letter words one keystroke in six costs zero time and output runs roughly 17%
faster than requested. pyautogui's per-call overhead pushes the other way.
`CALIBRATION_FACTOR = 34 / 50` at `main.py:172` is one constant papering over two errors
with opposite signs. Both disappear here.

- **Base rate** on the standard definition: 5 characters *including spaces* per word.
  Spaces are scheduled keystrokes like any other.
- **Jitter** drawn from a lognormal around the base interval. Human inter-key intervals
  are right-skewed — mostly tight, with occasional long tails. The current
  `random.uniform` over a symmetric range is flat, which reads as machine-generated.
- **Structural pauses** at word boundaries and after sentence-ending punctuation.

**Sentence-ending detection.** Double-space is applied only after a period that ends a
sentence, determined by what follows (whitespace then a capital) plus an abbreviation
exception list. The unconditional `if char == '.': press('space')` at `main.py:190`
breaks `Mr.`, `e.g.`, `3.14` and URLs, each scored as errors.

### 6.7 Calibration

One guided run replaces the hardcoded constant. The tool types a known passage into its
own text box at a requested rate, measures true wall-clock WPM, and derives a correction
factor for that machine, stored per-machine.

During real runs a closed loop compares elapsed against planned every N characters and
adjusts the remaining intervals. The per-step correction is clamped so convergence never
appears as a visible speed change.

### 6.8 Keystroke output (`adapters/keyboard.py`)

Every event stamped with the `dwExtraInfo` signature.

Character output resolves each character through `VkKeyScanW` to a virtual key plus
shift state, and sends genuine scan codes via `MapVirtualKey`.
`KEYEVENTF_UNICODE` is a **fallback only**, for characters the active layout cannot
produce. Unicode injection arrives as `VK_PACKET` (0xE7), and a web application reading
`keyCode` rather than `key` would see 231 instead of the letter. Scan-code output is
indistinguishable from a physical keyboard at the event level, and fixes pyautogui's
layout-dependent breakage on non-US layouts as a side effect.

Timing comes from `CreateWaitableTimerExW` with `CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`
(`adapters/clock.py`). Windows' default `time.sleep` granularity is about 15.6 ms, which
is 7% jitter on the roughly 218 ms interval of 55 WPM — enough to distort rhythm. A
waitable timer is preferred over `timeBeginPeriod(1)` because it does not change a global
system setting on the user's behalf.

### 6.9 Resume and resync

While paused, the low-level hook continues running and therefore observes what the user
types during manual catch-up. On resume, the tool matches those observed keystrokes
against the characters it was about to send and advances the cursor by however many
match. No re-OCR, no guessing.

If the observed keystrokes do not match — the user backspaced or corrected something —
it falls back to re-reading the target region rather than assuming. This makes
pause and resync the most reliable path in the design rather than the least.

## 7. Profiles, configuration and UI

### 7.1 Auto-detect

Grab the monitor, downscale, run Tesseract at block level via `image_to_data`, and score
candidate regions on word count, line count, aspect ratio and mean confidence. A passage
block scores clearly above navigation chrome or a sidebar. The best candidate is proposed
with its outline drawn.

This requires morphological grouping for robustness, and section 6.2 requires adaptive
thresholding. Both are a few lines in OpenCV and a fiddly numpy reimplementation
otherwise. **Decision: add `opencv-python-headless`** and accept about 40 MB. It is used
twice over and packaging size is not a constraint.

### 7.2 Region adjustment

Keyboard-only. Arrow keys move an edge, Shift plus arrows resize, Tab cycles the active
edge. No dragging anywhere in the application.

A panel shows **live OCR output of the current region** while adjusting, so the user
adjusts until the text reads correctly rather than until the box looks right.

This replaces `ScreenSelector` entirely, which also removes its mixed coordinate spaces
(`canvasx` on press at `main.py:238`, raw `event.x` on release at `main.py:245`) and its
missing Escape binding.

### 7.3 Profiles

Named, one per test site. Each stores the region in physical virtual-desktop pixels, the
monitor's identity so a profile does not silently point at the wrong screen after
docking, target WPM, OCR parameters, and whether the passage scrolls.

### 7.4 Configuration storage

Moves to `%APPDATA%\TypingAssistant\`. Today `config.json` is read from the current
working directory (`main.py:21`), so running the tool from anywhere but its own folder
silently creates a fresh config — and it blocks packaging outright.

The new format is versioned and typed, with a migration that reads the existing file,
including its string-typed numbers (`"wpm": "90"`) that the current code defensively
converts with `float()` in five places.

### 7.5 Tesseract discovery

Replaces the hardcoded path at `main.py:18`. Check a bundled copy, then `PATH`, then
common install locations. On failure, report it in the UI with a download link rather
than dying on an exception the user never sees.

### 7.6 Status and logging

Every `print()` today goes to a console the user must keep open. Replaced by an
always-on-top indicator pill showing state, progress through the passage, and *measured*
WPM alongside target, plus a rotating log file.

The pill is click-through and never takes focus. The current notification
`CTkToplevel` (`main.py:220`) can steal focus at exactly the wrong moment.

### 7.7 UI accessibility

Every action reachable by key. Minimum 44 px hit targets. Scalable font. High-contrast
theme. Visible focus. No hover-only affordances. No timed interactions anywhere.

### 7.8 First run

A three-screen wizard: find Tesseract, run calibration, create the first profile with
auto-detect.

## 8. Spike results (completed 2026-09-14)

Throwaway `ctypes` probe, Python 3.11 x64, Windows 11 26200. `WH_KEYBOARD_LL` hook plus
`SendInput` of `VK_F24` (chosen so no text entered any window).

```
tagged synthetic   vk=0x87  flags=0x10  injected=True   dwExtraInfo=0x54595041
real keypress      vk=0x09  flags=0x00  injected=False  dwExtraInfo=0x0
throughput         600/600 events carried the tag (100%)
elevated=False     hook installed and observed everything anyway
```

1. The tag round-trips intact, 600 of 600 under load.
2. `LLKHF_INJECTED` is an independent second discriminator — set on all synthetic
   events, clear on real ones.
3. **No Administrator required.** The hook installed and functioned unelevated.
   Elevation matters only for typing into an elevated window, which a browser is not.
   The "Run as administrator" instruction in the user guide is removed.
4. `SendInput` overhead is 1.8 ms per keystroke, against about 218 ms per character at
   55 WPM — 0.8%. This confirms `CALIBRATION_FACTOR` was compensating for pyautogui,
   not for the operating system.

Finding 3 also removes a security smell: the tool no longer asks users to run an
executable as Administrator.

## 9. Testing strategy

### 9.1 Unit tests

Pure functions, fast, deterministic. `pacing.py` gets the sentence-ending rule as an
explicit case table — `Mr. Smith`, `e.g. this`, `3.14`, `https://x.com/a.b`,
`End. Next` — plus seeded-RNG determinism and a check that a schedule's total duration
matches the requested WPM. `text.py` gets a normalization table. `correction.py` gets
both repair cases and must-not-corrupt cases.

### 9.2 Property tests

The cursor invariant is verified with Hypothesis. Generate arbitrary sequences of OCR
reads — truncated, duplicated, reordered, character-corrupted — and assert that emitted
output is **always** a strict extension of what was already emitted, never a
re-emission, under any input.

### 9.3 Golden-image tests

Real screenshots committed as PNG fixtures with expected text. Includes mid-test frames
where typing.com has recolored already-typed words, since that recoloring is the flicker
that breaks the current implementation.

### 9.4 Fake adapters

`FakeKeyboard` records what would have been sent. `FakeCapture` serves fixture images.
`FakeClock` makes pacing tests finish instantly. The full pipeline runs end-to-end in CI
with no real screen and no real keystrokes. Abort latency is asserted here.

### 9.5 Local practice target (`tools/practice/`)

A self-hosted HTML page imitating a typing test: displays a passage, scrolls a fixed line
window as typing.com does, recolors text as it is typed, and records every keystroke with
a timestamp. It provides unlimited free end-to-end runs, objective measured WPM and
accuracy, a keystroke-timing log for comparing rhythm against a recording of real human
typing, and deliberate reproduction of scroll jumps, recolor and mid-word wrapping.

### 9.6 Acceptance criteria

| Criterion | Target |
|---|---|
| Measured WPM vs. target, on the practice page | within 2 WPM |
| Duplicate words across 100 runs with injected OCR noise | zero |
| Abort latency | 1 keystroke or less |
| Post-correction OCR accuracy on golden fixtures | 99.5% or better |
| Runs with no interruption prompt, on a clean capture | 90% or better |

### 9.7 CI and manual checklist

GitHub Actions on `windows-latest` running unit, property, golden and fake-adapter
suites. A written manual checklist covers what cannot be automated: DPI at 100, 125, 150
and 200%, two monitors with *different* scaling, and pause-then-resync performed by hand.

## 10. Defect register

Every defect found in the current implementation, and where it is addressed.

| # | Defect | Location | Addressed in |
|---|---|---|---|
| 1 | No panic stop; `FAILSAFE=False` and the hotkey returns early while typing | `main.py:15`, `:64` | 5.3 |
| 2 | No DPI awareness; wrong region on scaled displays | `main.py:83` | 6.1 |
| 3 | Clamping uses primary-monitor size; second-monitor regions crop | `main.py:83` | 6.1 |
| 4 | Selector mixes coordinate spaces (`canvasx` on press, `event.x` on release) | `main.py:238`, `:245` | 7.2 |
| 5 | No Escape binding despite the guide claiming cancellation | `main.py:234` | 7.2 |
| 6 | `CALIBRATION_FACTOR` is a machine-specific magic constant | `main.py:172` | 6.6, 6.7 |
| 7 | Spaces incur no delay, inflating actual WPM about 17% | `main.py:199` | 6.6 |
| 8 | Unconditional double-space after every period | `main.py:190` | 6.6 |
| 9 | `text.split()` destroys newlines and whitespace structure | `main.py:178` | 6.3 |
| 10 | `replace('  ', ' ')` collapses only once | `main.py:123` | 6.3 |
| 11 | Simulated mistakes lower the real keystroke-scored result | `main.py:181` | 5.3 (removed) |
| 12 | OCR discards per-word confidence; no gate possible | `main.py:122` | 6.2 |
| 13 | No upscaling or thresholding before OCR | `main.py:120` | 6.2 |
| 14 | `difflib` `replace` opcode re-emits already-typed words | `main.py:151` | 6.5 |
| 15 | Non-atomic check-then-set on `is_typing_event` | `main.py:160` | 5.1 |
| 16 | Config reloaded from disk inside the typing path | `main.py:164` | 5.1 |
| 17 | Fixed, uncancellable 8-second countdown | `main.py:95` | 5.2 |
| 18 | Hardcoded Tesseract path | `main.py:18` | 7.5 |
| 19 | Config read from the current working directory | `main.py:21` | 7.4 |
| 20 | All errors go to `print()` on a console that must stay open | throughout | 7.6 |
| 21 | Notification toplevel can steal focus | `main.py:220` | 7.6 |
| 22 | `requirements.txt` omits `pyautogui`; guide tells users to pip it manually | `requirements.txt` | 11 |
| 23 | Unnecessary Administrator requirement | Users Guide | 8, finding 3 |
| 24 | Documentation describes features that do not exist (pause hotkey, Live Control window, Save button) | Users Guide | 11 |
| 25 | No tests, no CI, no README.md, no packaging | repo | 9, 11 |

## 11. Licence, packaging and documentation

- **Licence: 0BSD** (Zero-Clause BSD), chosen as the most permissive workable option.
  It grants use, copying, modification and distribution with no attribution requirement
  and no obligation to reproduce the licence, is OSI-approved and SPDX-recognized, and
  retains the warranty and liability disclaimer. CC0 and the Unlicense are marginally
  more permissive in principle, but CC0 explicitly withholds patent rights and the
  Unlicense's drafting is rejected by some corporate legal teams, so both can reduce
  real-world reuse. The disclaimer carries weight here specifically because this
  software drives the user's keyboard.
- `requirements.txt` replaced by proper dependency declaration with every dependency
  pinned. `pyautogui` is dropped; `opencv-python-headless` is added.
- `README.md` written, so GitHub renders it. `Users Guide.txt` is rewritten to describe
  software that actually exists, and the Administrator instruction is removed.
- A single-file distributable so installation does not require a Python toolchain.
- `As Built.docx` and the current `Users Guide.txt` are retained in a `docs/legacy/`
  folder for history.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Low-level hook latency budget (about 300 ms) exceeded by a slow callback | Callback appends to a list and returns; no work in the hook |
| Antivirus or EDR flags a keyboard hook plus synthetic input | Expected; documented. Not mitigable without code signing, which is out of scope |
| OCR auto-correction corrupts text that was already correct | Must-not-corrupt test cases (9.1); correction applies only below the confidence threshold |
| Auto-detect picks the wrong block on a busy page | Keyboard nudge with live OCR preview (7.2); profiles persist the corrected region |
| Scan-code output still misbehaves on some web target | Practice target (9.5) measures it before a real test is attempted |

## 13. Out of scope

- Code signing.
- Cross-platform support.
- A native accessible UI toolkit. The boundary in section 5 makes this a later,
  contained change.
