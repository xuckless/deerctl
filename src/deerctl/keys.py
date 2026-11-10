"""Key vocabulary: physical key ids and remap targets.

A remap *target* is what a key sends. On the wire it is (cmd, code, type):
  type 0  plain HID usage          slot = [cmd, 0, code, 0, 0]
  type 1  modifier bitmask / Fn    slot = [cmd, code, 0, 0, 0]
  type 2  keyboard function        slot = [cmd, code, 0, 0, 0]
  type 3  consumer / mouse         slot = [cmd, 0, 0, 0, 0]
(These match the Drunkdeer Antler web driver's sendRemapKeyData.)
"""
from __future__ import annotations

from dataclasses import dataclass

KEY = 252  # cmd for normal key output


@dataclass(frozen=True)
class Target:
    name: str
    cmd: int
    code: int
    type: int
    label: str
    group: str

    def slot(self) -> list[int]:
        if self.type == 0:
            return [self.cmd, 0, self.code, 0, 0]
        if self.type in (1, 2):
            return [self.cmd, self.code, 0, 0, 0]
        return [self.cmd, 0, 0, 0, 0]

    def as_json(self) -> dict:
        return {"cmd": self.cmd, "code": self.code, "type": self.type}


_T: list[Target] = []


def _add(group, name, cmd, code, typ, label=None):
    _T.append(Target(name, cmd, code, typ, label or name, group))


# --- Letters / digits / punctuation -------------------------------------------
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _add("Letters", ch, KEY, 4 + i, 0, ch.upper())
for i, ch in enumerate("1234567890"):
    _add("Numbers", ch, KEY, 30 + i, 0)
for name, code, label in [
    ("enter", 40, "Enter"), ("esc", 41, "Esc"), ("backspace", 42, "Bksp"),
    ("tab", 43, "Tab"), ("space", 44, "Space"), ("minus", 45, "-"),
    ("equal", 46, "="), ("lbracket", 47, "["), ("rbracket", 48, "]"),
    ("backslash", 49, "\\"), ("iso-hash", 50, "# (ISO)"), ("semicolon", 51, ";"),
    ("quote", 52, "'"), ("grave", 53, "`"), ("comma", 54, ","),
    ("period", 55, "."), ("slash", 56, "/"), ("capslock", 57, "Caps"),
]:
    _add("Basic", name, KEY, code, 0, label)

# --- Function / navigation ----------------------------------------------------
for i in range(12):
    _add("Function", f"f{i + 1}", KEY, 58 + i, 0, f"F{i + 1}")
for i in range(12):
    _add("Function", f"f{i + 13}", KEY, 104 + i, 0, f"F{i + 13}")
for name, code, label in [
    ("printscreen", 70, "PrtSc"), ("scrolllock", 71, "ScrLk"), ("pause", 72, "Pause"),
    ("insert", 73, "Ins"), ("home", 74, "Home"), ("pageup", 75, "PgUp"),
    ("delete", 76, "Del"), ("end", 77, "End"), ("pagedown", 78, "PgDn"),
    ("right", 79, "→"), ("left", 80, "←"), ("down", 81, "↓"), ("up", 82, "↑"),
    ("menu", 101, "Menu"),
]:
    _add("Navigation", name, KEY, code, 0, label)

# --- Keypad -------------------------------------------------------------------
_add("Keypad", "numlock", KEY, 83, 0, "NumLk")
for name, code, label in [("kp-slash", 84, "KP /"), ("kp-asterisk", 85, "KP *"),
                          ("kp-minus", 86, "KP -"), ("kp-plus", 87, "KP +"),
                          ("kp-enter", 88, "KP Ent"), ("kp-period", 99, "KP .")]:
    _add("Keypad", name, KEY, code, 0, label)
for i in range(1, 10):
    _add("Keypad", f"kp{i}", KEY, 88 + i, 0, f"KP {i}")
_add("Keypad", "kp0", KEY, 98, 0, "KP 0")

# --- International ------------------------------------------------------------
for name, code, label in [("iso-backslash", 100, "\\ (ISO)"), ("ro", 135, "Ro"),
                          ("kana", 136, "Kana"), ("yen", 137, "¥"),
                          ("henkan", 138, "Henkan"), ("muhenkan", 139, "Muhenkan")]:
    _add("International", name, KEY, code, 0, label)

# --- Modifiers ----------------------------------------------------------------
for name, code, label in [("lctrl", 1, "LCtrl"), ("lshift", 2, "LShift"),
                          ("lalt", 4, "LAlt"), ("rctrl", 16, "RCtrl"),
                          ("rshift", 32, "RShift"), ("ralt", 64, "RAlt"),
                          ("rwin", 128, "RWin")]:
    _add("Modifiers", name, KEY, code, 1, label)
_add("Modifiers", "lwin", KEY, 227, 0, "LWin")      # the official driver sends Win this way
_add("Modifiers", "fn", 255, 128, 1, "Fn")
_add("Modifiers", "fn2", 254, 128, 1, "Fn2")

# --- Media / mouse ------------------------------------------------------------
for name, code, label in [("vol-up", 144, "Vol +"), ("vol-down", 145, "Vol −"),
                          ("mute", 146, "Mute"), ("play-pause", 147, "Play/Pause"),
                          ("stop", 148, "Stop"), ("prev-track", 149, "Prev"),
                          ("next-track", 150, "Next")]:
    _add("Media", name, code, code, 3, label)
for name, code, label in [("mouse-left", 176, "M1"), ("mouse-right", 177, "M2"),
                          ("mouse-middle", 178, "M3"), ("wheel-up", 181, "Wheel ↑"),
                          ("wheel-down", 182, "Wheel ↓"), ("wheel-left", 183, "Wheel ←"),
                          ("wheel-right", 184, "Wheel →")]:
    _add("Mouse", name, code, code, 3, label)

# --- Keyboard functions -------------------------------------------------------
for name, code, label in [("led-toggle", 14, "LED on/off"), ("led-mode-cycle", 0, "LED mode ⟳"),
                          ("led-color-cycle", 9, "LED colour ⟳"), ("led-pause", 13, "LED pause"),
                          ("led-prev", 2, "LED prev"), ("led-next", 1, "LED next"),
                          ("led-bright-up", 4, "Bright +"), ("led-bright-down", 5, "Bright −"),
                          ("led-speed-up", 7, "Speed +"), ("led-speed-down", 8, "Speed −"),
                          ("win-lock", 16, "Win lock")]:
    _add("Keyboard", name, 251, code, 2, label)
_add("Keyboard", "rt-toggle", 253, 32, 2, "Rapid Trigger")
_add("Keyboard", "none", KEY, 0, 0, "(disabled)")

TARGETS: dict[str, Target] = {t.name: t for t in _T}

ALIASES = {
    "escape": "esc", "return": "enter", "bksp": "backspace", "del": "delete",
    "ins": "insert", "pgup": "pageup", "pgdn": "pagedown", "caps": "capslock",
    "ctrl": "lctrl", "shift": "lshift", "alt": "lalt", "win": "lwin", "super": "lwin",
    "cmd": "lwin", "meta": "lwin", "option": "lalt", "altgr": "ralt",
    "disable": "none", "off": "none", "backtick": "grave", "tilde": "grave",
}


def find_target(spec: str) -> Target:
    """Resolve a target name. Also accepts raw HID usages: 'hid:0x39' / 'hid:57'."""
    s = spec.strip().lower()
    s = ALIASES.get(s, s)
    if s in TARGETS:
        return TARGETS[s]
    if s.startswith("hid:"):
        code = int(s[4:], 0)
        if not 0 <= code <= 255:
            raise ValueError("HID usage must be 0..255")
        return Target(s, KEY, code, 0, f"HID {code:#04x}", "Raw")
    raise KeyError(f"unknown key/target {spec!r} (see `deerctl keys`)")


def target_from_slot(cmd: int, code: int, typ: int) -> Target | None:
    for t in _T:
        if t.cmd == cmd and t.code == code and t.type == typ:
            return t
    if cmd == KEY and typ == 0:
        return Target(f"hid:{code:#04x}", KEY, code, 0, f"HID {code:#04x}", "Raw")
    return None


# --- Physical keys (names from the driver's m_kbdLayout) -----------------------
PHYS = {
    "ESC": ("esc", "Esc"), "MINUS": ("minus", "-"), "PLUS": ("equal", "="),
    "BACK": ("backspace", "Bksp"), "DELETE": ("delete", "Del"), "TAB": ("tab", "Tab"),
    "BRKTS_L": ("lbracket", "["), "BRKTS_R": ("rbracket", "]"),
    "SLASH_K29": ("backslash", "\\"), "END": ("end", "End"), "HOME": ("home", "Home"),
    "INSERT": ("insert", "Ins"), "CAPS": ("capslock", "Caps"),
    "COLON": ("semicolon", ";"), "QOTATN": ("quote", "'"), "EUR_K42": ("iso-hash", "#"),
    "RETURN": ("enter", "Enter"), "PAGEUP": ("pageup", "PgUp"), "PAGEDW": ("pagedown", "PgDn"),
    "SHF_L": ("lshift", "Shift"), "EUR_K45": ("iso-backslash", "\\"),
    "COMMA": ("comma", ","), "PERIOD": ("period", "."), "VIRGUE": ("slash", "/"),
    "SHF_R": ("rshift", "Shift"), "ARR_UP": ("up", "↑"), "ARR_DW": ("down", "↓"),
    "ARR_L": ("left", "←"), "ARR_R": ("right", "→"), "CTRL_L": ("lctrl", "Ctrl"),
    "CTRL_R": ("rctrl", "Ctrl"), "WIN_L": ("lwin", "Win"), "ALT_L": ("lalt", "Alt"),
    "ALT_R": ("ralt", "Alt"), "SPACE": ("space", ""), "FN1": ("fn", "Fn"),
    "FN2": ("fn2", "Fn2"), "APP": ("menu", "Menu"), "PRINT": ("printscreen", "PrtSc"),
    "SWUNG": ("grave", "`"), "NUMS": ("numlock", "Num"), "KP_DEL": ("kp-period", "KP ."),
    "JAP_1_K56": ("ro", "Ro"), "JAP_3_K14": ("yen", "¥"),
}


def phys_id(raw: str) -> tuple[str, str]:
    """Driver layout name -> (stable id, short label)."""
    if raw in PHYS:
        return PHYS[raw]
    if raw.startswith("KP") and raw[2:].isdigit():
        return (raw.lower(), "KP " + raw[2:])
    return (raw.lower(), raw)


# Approximate key widths (in units) for drawing the keyboard.
WIDTH = {"BACK": 2, "TAB": 1.5, "SLASH_K29": 1.5, "CAPS": 1.75, "RETURN": 2.25,
         "SHF_L": 2.25, "SHF_R": 1.75, "CTRL_L": 1.25, "WIN_L": 1.25, "ALT_L": 1.25,
         "SPACE": 6.25, "ALT_R": 1, "FN1": 1, "FN2": 1, "CTRL_R": 1}
