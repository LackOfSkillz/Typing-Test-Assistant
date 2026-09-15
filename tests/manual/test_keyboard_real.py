"""Real SendInput checks. Run explicitly: pytest tests/manual -m manual -s

VK_F24 is used wherever possible so no text lands in whatever window has focus.
"""

from __future__ import annotations

import ctypes

import pytest

from typing_assistant.adapters.keyboard import INPUT, SendInputKeyboard, _key_event

pytestmark = pytest.mark.manual

VK_F24 = 0x87


def test_input_struct_size_is_correct_for_this_architecture():
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(INPUT) == expected


def test_sendinput_accepts_our_event_structs():
    """SendInput returns how many events it accepted; a bad struct is short."""
    kb = SendInputKeyboard()
    scan = ctypes.WinDLL("user32").MapVirtualKeyW(VK_F24, 0)
    count = kb._send(
        _key_event(VK_F24, scan, up=False), _key_event(VK_F24, scan, up=True)
    )
    assert count == 2, f"SendInput accepted {count} of 2 events"


def test_send_vk_on_an_inert_key_does_not_raise():
    SendInputKeyboard().send_vk(VK_F24)


def test_ascii_characters_need_no_unicode_fallback():
    """Every printable ASCII character must resolve to a real virtual key."""
    user32 = ctypes.WinDLL("user32")
    user32.VkKeyScanW.argtypes = (ctypes.c_wchar,)
    user32.VkKeyScanW.restype = ctypes.c_short

    unresolvable = []
    needs_altgr = []
    for code in range(0x20, 0x7F):
        ch = chr(code)
        result = user32.VkKeyScanW(ch)
        if result == -1:
            unresolvable.append(ch)
        elif (result >> 8) & 0x06:  # ctrl or alt required
            needs_altgr.append(ch)

    print(f"\n  unresolvable: {unresolvable}")
    print(f"  need ctrl/alt (will use Unicode fallback): {needs_altgr}")
    assert unresolvable == [], f"active layout cannot produce: {unresolvable}"
