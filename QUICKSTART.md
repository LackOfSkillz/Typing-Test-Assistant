# Quick Start

Getting from nothing to your first successful run. This covers **v1**, the code that is
in the repository now. About fifteen minutes, most of it installing Tesseract.

If anything here doesn't match what you see, trust what you see and open an issue —
this file is meant to describe reality.

---

## Before you start: know how to stop it

v1 has **no panic stop**. Once it begins typing, the hotkey is ignored and it will type
the whole passage. Set this up first, before your first run:

1. Press `Ctrl+Shift+Esc` to open Task Manager. Leave it open on a second monitor, or
   just know the shortcut.
2. The process to end is **Python** or **python.exe**.

Practice it once on a scratch text file before you use this on anything that matters.

---

## 1. Install Tesseract

Download the installer from the
[UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) and accept the
default install location:

```
C:\Program Files\Tesseract-OCR\
```

v1 has that path hardcoded. If you install elsewhere, open `main.py` and edit line 18
to match.

## 2. Install the tool

```
git clone https://github.com/LackOfSkillz/Typing-Test-Assistant.git
cd Typing-Test-Assistant
pip install -r requirements.txt
```

## 3. Start it

```
python main.py
```

The console prints the active hotkeys. **Leave this window open** — it's the only place
the tool tells you anything. Move it somewhere you can see it.

## 4. Set your speed

Press `Ctrl+Alt+G` for settings.

| Field | Put this in |
|---|---|
| Average Words Per Minute | Start at `40`. See step 7 about why this number is approximate. |
| Speed Variation (%) | `10` |
| Accuracy (%) | `100` |

Set **Accuracy to 100**. Anything lower makes the tool type wrong characters on purpose
and backspace them, which lowers your real score on most tests rather than helping.

Close the window with the **X** to save.

## 5. Do a dry run on a text file

Don't start with a real test. Open Notepad, then:

1. Put some text on screen that you want typed — a paragraph from anywhere.
2. Press `Ctrl+Alt+]`. The screen dims and the cursor becomes a crosshair.
3. **Click and drag** a box around the text. Hold the button down through the whole
   drag; releasing early ends the selection where you let go.
4. You now have **8 seconds**. Click inside Notepad so it has focus.
5. Typing begins.

If nothing happens, check the console — OCR failures and errors are reported there and
nowhere else.

## 6. Stop it

Press `Ctrl+Alt+]` again to stop the scroll monitoring.

This works when it is *watching*, not while it is *typing*. Mid-typing, Task Manager is
your only option. This is the single worst rough edge in v1.

## 7. Calibrate your speed number by hand

The WPM setting doesn't produce that WPM. There's a hardcoded calibration constant tuned
on one machine, and spaces are typed with no delay at all, which alone runs output about
17% fast.

So measure it: run a real timed test once, note the WPM it reports, and adjust the
setting by the difference. If you set 40 and the test reports 52, set it to about 31 to
land near 40. The ratio holds well enough to work from, and it's specific to your
machine.

## 8. Things that will bite you

| Symptom | Cause |
|---|---|
| Captured area doesn't match what you selected | Windows display scaling isn't 100%. Set the display to 100%, or select a wider box than you need. |
| Wrong region entirely on a second monitor | Known v1 bug. Use the primary monitor. |
| `Mr.` and `3.14` come out with extra spaces | Every period gets a double space in v1. |
| A word or phrase gets typed twice | Scroll-tracking flicker. The most disruptive v1 bug. Stop and restart. |
| Paragraph breaks vanish | v1 collapses all text to single-spaced words. |
| Nothing typed, no error | Region captured no readable text. Select a tighter box around just the text. |
| Antivirus warning | It generates synthetic keystrokes. Expected. |

---

## Getting a better result

- **Select a tight box** around only the passage. Buttons, timers and navigation text
  in the box become typed garbage.
- **Bigger text OCRs better.** Zoom the page in before you select. Browser zoom at
  125–150% noticeably improves accuracy.
- **High contrast helps.** Plain black-on-white beats a styled or low-contrast theme.
- **Use the primary monitor at 100% scaling** until the v2 capture fix lands.

Most of these workarounds exist because of v1 limitations that v2 removes — see the
[README](README.md#known-limitations-in-v1) and the
[design spec](docs/superpowers/specs/2026-09-14-typing-assistant-redesign-design.md).
