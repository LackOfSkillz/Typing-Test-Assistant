# Typing Test Assistant

An assistive input tool for Windows. It reads a block of text from your screen and
types it for you, at a speed you choose.

It exists because typing tests are a barrier for people whose hands don't cooperate.
Limited manual dexterity is the design constraint throughout: sustained typing is the
problem, knowing what to type is not.

**Licence:** [0BSD](LICENSE) — use it, change it, ship it, sell it. No attribution
required, no conditions.

---

## Status

**v1 works and is what this document describes.** It is a single `main.py`, written in
early 2025, and it does the job with rough edges.

**v2 is in progress** — a rebuild around a testable core, with a real panic stop,
honest WPM, saved region profiles, and no click-and-drag anywhere. The design is
written up in
[`docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md`](docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md),
including a register of 25 defects in v1 and where each is being fixed.

Nothing below describes v2. If a feature isn't in this README, it isn't in the code yet.

---

## What it does

1. You press a hotkey and drag a box around the text you want typed.
2. It reads that text with OCR.
3. After an 8-second pause, it types the text into whatever window has focus.
4. It keeps watching that box, and types new text as the passage scrolls.

## Requirements

- **Windows**
- **Python 3.9+** — [python.org](https://www.python.org/downloads/)
- **Tesseract OCR** — [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki).
  v1 looks for it at exactly `C:\Program Files\Tesseract-OCR\tesseract.exe`. If you
  install it anywhere else, edit the path at the top of `main.py`.

## Install

```
git clone https://github.com/LackOfSkillz/Typing-Test-Assistant.git
cd Typing-Test-Assistant
pip install -r requirements.txt
```

## Run

```
python main.py
```

Leave the console window open — v1 reports everything it does there, and that console
is your only view of what's happening.

Administrator is **not** normally required. You only need it to type into a window that
is itself running elevated. The older guide said to always run as administrator; that
was over-cautious.

See [QUICKSTART.md](QUICKSTART.md) for the first-run walkthrough.

## Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Alt+]` | Start (select a region), or stop monitoring if already running |
| `Ctrl+Alt+G` | Show/hide the settings window |

Both are editable in the settings window. Hotkey changes need an app restart.

## Settings

| Setting | Meaning |
|---|---|
| Average Words Per Minute | Target speed. See the warning below — v1 does not hit this accurately. |
| Speed Variation (%) | How much the delay between keystrokes wobbles |
| Accuracy (%) | Chance per character of typing a wrong letter and backspacing it |

Settings save when you close the window with the X.

## Known limitations in v1

These are real and worth knowing before you rely on it. All are addressed in the v2 design.

- **There is no panic stop.** Once typing starts, the hotkey is ignored and the
  failsafe is disabled. To stop it early you must kill the Python process. Know how
  you'll do that before you start a real test.
- **The WPM number is not accurate.** A hardcoded calibration constant, tuned on one
  machine, plus spaces being typed with no delay at all, mean actual speed differs from
  the setting — roughly 17% fast from the spaces alone.
- **Scaled displays capture the wrong region.** If Windows display scaling is not 100%,
  the captured area won't match what you selected. Multi-monitor setups have the same
  problem on the secondary screen.
- **Every period gets a double space.** That breaks `Mr.`, `e.g.`, `3.14` and URLs, and
  each one counts as errors.
- **The Accuracy setting lowers your real score.** It types a wrong character and
  backspaces it. Most typing tests count keystrokes, so this makes results worse rather
  than more convincing. Set it to 100 unless you specifically want the behavior. It is
  removed entirely in v2.
- **OCR mistakes get typed as-is.** There is no review step and no correction pass, so
  `rn` read as `m` becomes a typed error.
- **It can retype text it already typed.** The scroll-tracking diff accepts replaced
  words, so one OCR flicker can duplicate output mid-test. This is the most disruptive
  bug in v1.
- **Line breaks and paragraph structure are discarded.** Everything is typed as a single
  run of words separated by single spaces.
- **`config.json` is read from the current directory.** Run the tool from somewhere else
  and it silently starts from defaults.

## A note on antivirus

The tool generates synthetic keystrokes and, in v2, installs a keyboard hook. That is
structurally what a keylogger looks like, and some antivirus and EDR products will say
so. The code is short and readable if you want to check it yourself.

## Contributing

The v2 design spec is the place to start; it explains the architecture and why each
decision was made. Bug reports about v1 are welcome but check the limitations list
above first — most known problems are already catalogued there and in the spec.

`docs/legacy/` holds the original v1 documentation. Note that the original user guide
describes a pause-and-resync feature, a "Live Control" window and a Save button that
were never implemented.
