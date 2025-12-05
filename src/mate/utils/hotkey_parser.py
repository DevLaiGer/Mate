"""Parse keyboard library format strings into Win32 hotkey codes."""

from __future__ import annotations

# Win32 Virtual Key Codes
VK_CODES: dict[str, int] = {
    # Letters
    "a": 0x41,
    "b": 0x42,
    "c": 0x43,
    "d": 0x44,
    "e": 0x45,
    "f": 0x46,
    "g": 0x47,
    "h": 0x48,
    "i": 0x49,
    "j": 0x4A,
    "k": 0x4B,
    "l": 0x4C,
    "m": 0x4D,
    "n": 0x4E,
    "o": 0x4F,
    "p": 0x50,
    "q": 0x51,
    "r": 0x52,
    "s": 0x53,
    "t": 0x54,
    "u": 0x55,
    "v": 0x56,
    "w": 0x57,
    "x": 0x58,
    "y": 0x59,
    "z": 0x5A,
    # Numbers
    "0": 0x30,
    "1": 0x31,
    "2": 0x32,
    "3": 0x33,
    "4": 0x34,
    "5": 0x35,
    "6": 0x36,
    "7": 0x37,
    "8": 0x38,
    "9": 0x39,
    # Function keys
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    # Arrow keys
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    # Special keys
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "page up": 0x21,
    "page down": 0x22,
    "pgup": 0x21,
    "pgdn": 0x22,
}

# Win32 Modifier Flags
MOD_NONE = 0x0000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008


class ParsedHotkey:
    """Parsed hotkey with Win32 modifiers and virtual key code."""

    def __init__(self, modifiers: int, vk_code: int) -> None:
        self.modifiers = modifiers
        self.vk_code = vk_code

    def __repr__(self) -> str:
        mods = []
        if self.modifiers & MOD_CONTROL:
            mods.append("CTRL")
        if self.modifiers & MOD_ALT:
            mods.append("ALT")
        if self.modifiers & MOD_SHIFT:
            mods.append("SHIFT")
        if self.modifiers & MOD_WIN:
            mods.append("WIN")
        return f"ParsedHotkey(modifiers={'+'.join(mods) if mods else 'NONE'}, vk=0x{self.vk_code:02X})"


def parse_hotkey(shortcut: str) -> ParsedHotkey:
    """
    Parse a keyboard library format string into Win32 hotkey format.

    Examples:
        "ctrl+shift+z" -> ParsedHotkey(MOD_CONTROL | MOD_SHIFT, VK_Z)
        "alt+x" -> ParsedHotkey(MOD_ALT, VK_X)
        "ctrl+shift+up" -> ParsedHotkey(MOD_CONTROL | MOD_SHIFT, VK_UP)

    Args:
        shortcut: Keyboard library format string (e.g., "ctrl+shift+z")

    Returns:
        ParsedHotkey with modifiers and virtual key code

    Raises:
        ValueError: If the shortcut cannot be parsed or contains invalid keys
    """
    parts = [p.strip().lower() for p in shortcut.split("+")]
    if not parts:
        raise ValueError(f"Empty shortcut: {shortcut}")

    modifiers = MOD_NONE
    vk_code: int | None = None

    for part in parts:
        if part in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part in ("shift", "shft"):
            modifiers |= MOD_SHIFT
        elif part in ("win", "windows", "cmd", "super", "meta"):
            modifiers |= MOD_WIN
        elif part in VK_CODES:
            if vk_code is not None:
                raise ValueError(f"Multiple keys found in shortcut: {shortcut}")
            vk_code = VK_CODES[part]
        else:
            # Try to find a case-insensitive match
            found = False
            for key, code in VK_CODES.items():
                if key.lower() == part.lower():
                    if vk_code is not None:
                        raise ValueError(f"Multiple keys found in shortcut: {shortcut}")
                    vk_code = code
                    found = True
                    break
            if not found:
                raise ValueError(f"Unknown key in shortcut: {part} (from {shortcut})")

    if vk_code is None:
        raise ValueError(f"No key found in shortcut: {shortcut}")

    return ParsedHotkey(modifiers, vk_code)

