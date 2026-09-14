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

## Driving it from automation

Two input paths, verified:

- **`keydown`** is the primary path. Real keystrokes — human hands, and `SendInput`
  from the tool itself — arrive this way and carry per-keystroke timing. This is the
  path Plan 2's end-to-end tests exercise.
- **`beforeinput` on the hidden sink** is a fallback for synthetic text insertion that
  produces no `keydown` at all, such as CDP `Input.insertText`, IME composition, or
  paste. A batched insertion shares one timestamp, so only the `keydown` path gives
  usable rhythm data.

There is no double-counting: the `keydown` handler calls `preventDefault`, which
suppresses the following `beforeinput` for real keystrokes.

Two gotchas when driving it with CDP-based tooling:

- Named keys need **DOM** names, not X11 names. `Backspace` and `Enter` work;
  `BackSpace` and `Return` produce a `keydown` with `key`, `code` and `keyCode` all
  empty, which no handler can act on.
- Focus the sink first (`document.getElementById('sink').focus()`), or clicks and
  keystrokes land nowhere.

## Passages

- `plain` — ordinary prose
- `punctuation-traps` — `Mr.`, `3.14`, `e.g.`, a URL. Exercises the sentence-ending
  rule; a naive double-space after every period fails this passage visibly.
- `long-scroll` — long enough to force several scroll steps
