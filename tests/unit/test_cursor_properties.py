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
