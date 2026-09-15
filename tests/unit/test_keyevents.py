from __future__ import annotations

from typing_assistant.core.keyevents import (
    LLKHF_INJECTED,
    LLKHF_UP,
    SIGNATURE,
    classify,
)

# Exactly what the spike observed (spec section 8).
TAGGED_DOWN = dict(vk=0x87, scan=0, flags=0x10, extra_info=SIGNATURE)
TAGGED_UP = dict(vk=0x87, scan=0, flags=0x90, extra_info=SIGNATURE)
HUMAN_DOWN = dict(vk=0x09, scan=0x0F, flags=0x00, extra_info=0x0)
HUMAN_UP = dict(vk=0x09, scan=0x0F, flags=0x80, extra_info=0x0)
OTHER_TOOL = dict(vk=0x41, scan=0x1E, flags=0x10, extra_info=0xDEADBEEF)


def test_signature_matches_the_validated_spike():
    assert SIGNATURE == 0x54595041


def test_our_tagged_event_is_recognised():
    e = classify(**TAGGED_DOWN)
    assert e.injected is True
    assert e.ours is True
    assert e.human is False


def test_real_keypress_is_human():
    e = classify(**HUMAN_DOWN)
    assert e.injected is False
    assert e.ours is False
    assert e.human is True


def test_another_tools_injection_is_not_ours_and_not_human():
    """Injected but unsigned: not our output, and not hands either."""
    e = classify(**OTHER_TOOL)
    assert e.injected is True
    assert e.ours is False
    assert e.human is False


def test_signature_without_the_injected_flag_is_not_ours():
    """Both discriminators are required, so the tag alone cannot be spoofed."""
    e = classify(vk=0x41, scan=0x1E, flags=0x00, extra_info=SIGNATURE)
    assert e.ours is False
    assert e.human is True


def test_key_up_and_down_are_distinguished():
    assert classify(**HUMAN_DOWN).is_down is True
    assert classify(**HUMAN_DOWN).is_up is False
    assert classify(**HUMAN_UP).is_up is True
    assert classify(**TAGGED_UP).is_up is True
    assert classify(**TAGGED_DOWN).is_down is True


def test_flag_constants():
    assert LLKHF_INJECTED == 0x10
    assert LLKHF_UP == 0x80


def test_event_is_frozen():
    e = classify(**HUMAN_DOWN)
    try:
        e.vk = 1  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("KeyEvent should be immutable")
