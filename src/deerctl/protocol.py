"""Drunkdeer keyboard protocol (reverse-engineered from the Antler web driver).

Every message is a 63-byte payload in HID output report 4; replies come back as
input report 4 with the same first byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources

from .hidio import PAYLOAD, DeviceError, HidDevice, drain

N_KEYS = 126          # 6 rows x 21 columns matrix
KEYS_PER_PACKET = 9   # 14 packets per layer
LAYERS = {"base": 1, "fn1": 2, "fn2": 3}

_DB = json.loads(resources.files(__package__).joinpath("models.json").read_text("utf-8"))
MODELS = _DB["models"]


def _pkt(*head: int) -> bytearray:
    b = bytearray(PAYLOAD)
    b[: len(head)] = bytes(head)
    return b


@dataclass
class Model:
    name: str
    ktype: int
    layout: list[str]                     # 126 driver key names ("" = no key)
    defaults: dict[int, list[int] | None]  # matrix index -> 5-byte slot (base layer)

    @classmethod
    def from_identity(cls, ident: tuple[int, int, int]) -> "Model":
        for m in MODELS:
            if list(ident) in m["ids"]:
                return cls.from_entry(m)
        raise DeviceError(f"Unknown keyboard identity {ident}; not in the model table.")

    @classmethod
    def by_name(cls, name: str) -> "Model":
        for m in MODELS:
            if m["name"].lower() == name.lower():
                return cls.from_entry(m)
        raise KeyError(name)

    @classmethod
    def from_entry(cls, m) -> "Model":
        from .keys import Target
        d = {}
        for e in m["defaults"]["0"]:
            d[e["i"]] = Target("", e["cmd"], e["code"], e["type"], "", "").slot()
        return cls(m["name"], m["ktype"], m["layout"], d)


@dataclass
class Info:
    identity: tuple[int, int, int]
    firmware: int
    firmware_str: str
    turbo: int
    rapid_trigger: int
    rdt: int
    lw: int
    rt_match: int
    raw: bytes = field(repr=False)


# Actuation encodings. (cmd, bytes per value, scale, ap_max, rt_max)
FINE = ("fine", 253, 2, 200, 3.3, 3.1)      # uint16 LE, 0.005 mm
OLD_HP = ("old_hp", 182, 1, 100, 2.0, 2.0)  # byte, 0.01 mm, UI caps at 2.0 mm
BASIC = ("basic", 182, 1, 10, 3.3, 3.1)     # byte, 0.1 mm
AP_MIN = 0.2

_HP_FROM = {75: 35, 750: 17, 751: 25, 752: 25, 65: 19, 60: 21, 754: 13, 755: 6}
_ALWAYS_OLD_HP = {651, 652, 653, 600, 601, 602}
_ALWAYS_FINE = {756, 757, 603}


def actuation_mode(ktype: int, fw: int):
    if ktype in _ALWAYS_FINE:
        return FINE
    if ktype in _ALWAYS_OLD_HP:
        return OLD_HP
    if ktype in _HP_FROM and fw >= _HP_FROM[ktype]:
        return OLD_HP
    return BASIC


# --- lighting -------------------------------------------------------------------
PRESET_COLOURS = {"red": "ff0000", "green": "00ff00", "blue": "0000ff", "yellow": "ffff00",
                  "purple": "ff00ff", "cyan": "00ffff", "white": "ffffff"}
EFFECT_NAMES = {
    "color1": "off", "color2": "rotate", "color3": "wave", "color4": "surf-right",
    "color5": "breath", "color6": "surf-center", "color7": "spectrum", "color8": "ripple",
    "color9": "static", "color10": "reactive", "color11": "serpentine", "color12": "fountain",
    "color13": "laser", "color14": "fish", "color15": "surf-cross", "color16": "heart",
    "color17": "traffic", "color18": "snake", "color19": "raindrops", "color20": "turbo",
    "color21": "custom", "color22": "stars", "color23": "surf-down", "color24": "surf-repeat",
    "color25": "random-fountain", "color26": "demons",
}


def _model_entry(model: "Model") -> dict:
    return next(m for m in MODELS if m["name"] == model.name)


def effects(model: "Model", fw: int) -> dict[str, dict]:
    """Effect name -> {mode, colourful, preset} for this model/firmware (as the web driver computes it)."""
    table = _model_entry(model)["lighting"]
    fine = actuation_mode(model.ktype, fw) is FINE
    shift = 2 if any(e["title"] == "color20" for e in table) else 0
    out = {}
    for pos, e in enumerate(table):
        name = EFFECT_NAMES.get(e["title"], e["title"])
        if name in ("turbo", "custom"):
            continue
        mode = e["code"] if fine and e["code"] is not None else max(0, pos - shift)
        out[name] = {"mode": mode, "colourful": bool(e["colourful"]), "preset": bool(e["preset"])}
    return out


def custom_mode(model: "Model", fw: int) -> tuple[int, int]:
    """(mode byte, packet count) for per-key custom colours."""
    fine = actuation_mode(model.ktype, fw) is FINE
    mode = 19 if fine else len(_model_entry(model)["lighting"]) - 2
    chunks = 6 if model.name.startswith(("G60", "G65")) else 7
    return mode, chunks


class Keyboard:
    def __init__(self, dev: HidDevice):
        self.dev = dev
        self.info: Info | None = None
        self.model: Model | None = None

    # -- transport --------------------------------------------------------------
    def transact(self, pkt: bytes, expect: int | None = None, timeout: float = 0.6,
                 retries: int = 2) -> bytes | None:
        expect = pkt[0] if expect is None else expect
        for _ in range(retries + 1):
            self.dev.write(bytes(pkt))
            data = self._wait(expect, timeout)
            if data is not None:
                return data
        raise DeviceError(f"Keyboard did not answer command 0x{pkt[0]:02x}")

    def _wait(self, expect: int, timeout: float) -> bytes | None:
        import time
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            data = self.dev.read(left)
            if data is None:
                return None
            if data and data[0] == expect:
                return data
        return None

    # -- commands ---------------------------------------------------------------
    def identify(self) -> Info:
        drain(self.dev)
        d = self.transact(_pkt(160, 2, 0))
        fw = int(f"{d[8]}{d[7]}")
        fw_str = f"0.{d[8]}{d[7]}"
        if d[34]:
            fw_str += f"-{d[34]:x}.{d[35]:x}.{d[36]:x}"
        self.info = Info((d[4], d[5], d[6]), fw, fw_str, d[15], d[16], d[18], d[19], d[30], bytes(d))
        self.model = Model.from_identity(self.info.identity)
        return self.info

    def write_layer(self, layer: int, slots: dict[int, list[int]]):
        """Write one full layer. `slots` maps matrix index -> 5-byte slot; missing = empty."""
        for p in range(1, 15):
            b = _pkt(160, 2, 4, p, 14, layer)
            r = 6
            for w in range(KEYS_PER_PACKET):
                i = (p - 1) * KEYS_PER_PACKET + w
                if i >= N_KEYS:
                    break
                s = slots.get(i)
                if s:
                    b[r] = i
                    b[r + 1: r + 6] = bytes(s)
                r += 6
            b[60] = 165
            self.transact(b)

    def set_rapid_trigger(self, enabled: bool):
        i = self.info
        lwrdt = (1 if i.lw else 0) | (2 if i.rdt else 0)
        b = _pkt(181, 0, 30, 1, 0, 0, 1, i.turbo, int(enabled), 0, lwrdt, i.rt_match)
        self.transact(b)
        i.rapid_trigger = int(enabled)

    def write_travel(self, kind: str, values: list[float]):
        """kind: 'actuation' | 'press' | 'release'; values: 126 floats in mm."""
        mode = actuation_mode(self.model.ktype, self.info.firmware)
        name, cmd, width, scale, ap_max, rt_max = mode
        sub = {"actuation": 1, "press": 4, "release": 5}[kind]
        lo, hi = (AP_MIN, ap_max) if kind == "actuation" else (0.0, rt_max)
        enc = [round(max(lo, min(hi, v)) * scale) for v in values]
        if width == 2:  # 5 packets: 30,30,30,30,6
            for c in range(5):
                b = _pkt(253, sub, c)
                n = 30 if c < 4 else 6
                for k in range(n):
                    v = enc[c * 30 + k]
                    b[3 + 2 * k], b[4 + 2 * k] = v & 0xFF, v >> 8
                self.transact(b)
        else:           # 3 packets: 59,59,8
            for c in range(3):
                b = _pkt(182, sub, 0, c)
                n, off = (59, c * 59) if c < 2 else (8, 118)
                for k in range(n):
                    b[4 + k] = min(255, enc[off + k])
                self.transact(b)

    # -- lighting ---------------------------------------------------------------
    def set_effect(self, mode: int, speed: int, brightness: int, colour: int):
        """Preset effect. colour: 0 = rainbow/default, 1..7 = PRESET_COLOURS."""
        self.transact(_pkt(174, 1, 0, 0, mode, speed, brightness, colour))

    def set_custom_colours(self, colours: dict[int, tuple[int, int, int]], brightness: int):
        """Per-key static colours: matrix index -> (r, g, b)."""
        mode, chunks = custom_mode(self.model, self.info.firmware)
        items = list(colours.items())
        for c in range(chunks):
            part = items[c * 13:(c + 1) * 13]
            b = _pkt(174, 1, 0, 0, mode, 6, brightness, 255)
            for k, (idx, (r, g, bl)) in enumerate(part):
                b[8 + 4 * k: 12 + 4 * k] = bytes((128 + idx, r, g, bl))
            b[8 + 4 * len(part)] = 0xFF
            self.transact(b)

    def factory_reset(self):
        self.dev.write(bytes(_pkt(170)))
        self._wait(170, 2.0)
