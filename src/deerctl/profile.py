"""Keymap profiles.

The keyboard can't report its current remap, so (exactly like the official web
driver, which keeps it in browser localStorage) the profile file is the source
of truth and "apply" rewrites every layer.

Profile file (JSON, human-editable), keys are physical key ids (`deerctl layout`):
{
  "model": "G65",
  "layers": {"base": {"capslock": "lctrl"}, "fn1": {"h": "left"}, "fn2": {}},
  "actuation": {"default": 1.5, "keys": {"w": 0.8}},
  "rapid_trigger": {"enabled": true, "press": 0.2, "release": 0.2, "keys": {}}
}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .keys import WIDTH, Target, find_target, phys_id
from .protocol import LAYERS, N_KEYS, PRESET_COLOURS, Keyboard, Model, effects


def parse_colour(c: str) -> tuple[int, int, int]:
    """'red' / '#ff8800' / 'ff8800' -> (r, g, b)."""
    c = PRESET_COLOURS.get(c.lower(), c).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"bad colour {c!r}; use a name ({', '.join(PRESET_COLOURS)}) or #rrggbb")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def config_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "deerctl"


def physical_keys(model: Model) -> list[dict]:
    """Physical keys of a model: [{id, label, index, row, col, width, raw}]."""
    out, seen = [], {}
    for i, raw in enumerate(model.layout):
        if not raw or i not in model.defaults:   # unpopulated matrix position
            continue
        pid, label = phys_id(raw)
        if pid in seen:                      # keep ids unique
            seen[pid] += 1
            pid = f"{pid}{seen[pid]}"
        else:
            seen[pid] = 1
        out.append({"id": pid, "label": label, "index": i, "row": i // 21, "col": i % 21,
                    "width": WIDTH.get(raw, 1), "raw": raw})
    return out


class Profile:
    def __init__(self, model: Model, data: dict | None = None, path: Path | None = None):
        self.model = model
        self.path = path or config_dir() / f"{model.name}.json"
        data = data or {}
        self.layers: dict[str, dict[str, str]] = {k: dict(data.get("layers", {}).get(k, {}))
                                                  for k in LAYERS}
        self.actuation = data.get("actuation")
        self.rapid_trigger = data.get("rapid_trigger")
        self.lighting = data.get("lighting")
        self.keys = physical_keys(model)
        self.by_id = {k["id"]: k for k in self.keys}

    # -- persistence --------------------------------------------------------
    @classmethod
    def load(cls, model: Model, path: Path | None = None) -> "Profile":
        p = path or config_dir() / f"{model.name}.json"
        data = json.loads(p.read_text()) if p.exists() else {}
        if data.get("model") and data["model"] != model.name:
            raise ValueError(f"{p} is for {data['model']}, but the keyboard is a {model.name}")
        prof = cls(model, data, p)
        prof.validate()
        return prof

    def to_json(self) -> dict:
        d = {"model": self.model.name, "layers": self.layers}
        if self.actuation:
            d["actuation"] = self.actuation
        if self.rapid_trigger:
            d["rapid_trigger"] = self.rapid_trigger
        if self.lighting:
            d["lighting"] = self.lighting
        return d

    def save(self, path: Path | None = None):
        p = path or self.path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n")
        tmp.replace(p)

    def validate(self):
        for layer, m in self.layers.items():
            for k, t in m.items():
                self.key(k)
                find_target(t)
        for section in (self.actuation, self.rapid_trigger, self.lighting):
            for k in (section or {}).get("keys", {}):
                self.key(k)
        lt = self.lighting or {}
        if lt.get("color") not in (None, "rainbow"):
            parse_colour(lt["color"])
        for c in lt.get("keys", {}).values():
            parse_colour(c)
        for f in ("brightness", "speed"):
            if not 0 <= int(lt.get(f, 0)) <= 9:
                raise ValueError(f"lighting {f} must be 0..9")

    # -- editing ------------------------------------------------------------
    def key(self, kid: str) -> dict:
        k = self.by_id.get(kid.lower())
        if k is None:
            raise KeyError(f"no key {kid!r} on the {self.model.name} (see `deerctl layout`)")
        return k

    def set(self, layer: str, kid: str, target: str | None):
        k = self.key(kid)["id"]
        if target is None:
            self.layers[layer].pop(k, None)
            return
        t = find_target(target)
        # mapping a base key back to its own default is the same as clearing it
        if layer == "base" and t.slot() == self.model.defaults.get(self.key(k)["index"]):
            self.layers[layer].pop(k, None)
        else:
            self.layers[layer][k] = t.name

    # -- building packets ---------------------------------------------------
    def slots(self, layer: str) -> dict[int, list[int]]:
        s = dict(self.model.defaults) if layer == "base" else {}
        for kid, tname in self.layers[layer].items():
            s[self.key(kid)["index"]] = find_target(tname).slot()
        return s

    def travel_values(self, section: dict, field: str, fallback: float) -> list[float]:
        dflt = section.get(field, section.get("default", fallback))
        vals = [float(dflt)] * N_KEYS
        for kid, v in section.get("keys", {}).items():
            if isinstance(v, dict):
                v = v.get(field, dflt)
            vals[self.key(kid)["index"]] = float(v)
        return vals

    def apply(self, kb: Keyboard, progress=None):
        steps = [("keymap", lambda: [kb.write_layer(n, self.slots(l)) for l, n in LAYERS.items()])]
        if self.actuation:
            steps.append(("actuation", lambda: kb.write_travel(
                "actuation", self.travel_values(self.actuation, "default", 2.0))))
        if self.rapid_trigger:
            rt = self.rapid_trigger
            if rt.get("enabled"):
                steps.append(("rt-press", lambda: kb.write_travel(
                    "press", self.travel_values(rt, "press", 0.3))))
                steps.append(("rt-release", lambda: kb.write_travel(
                    "release", self.travel_values(rt, "release", 0.3))))
            steps.append(("rapid-trigger", lambda: kb.set_rapid_trigger(bool(rt.get("enabled")))))
        if self.lighting:
            steps.append(("lighting", lambda: self.apply_lighting(kb)))
        for name, fn in steps:
            if progress:
                progress(name)
            fn()

    def uses_custom_colours(self) -> bool:
        lt = self.lighting or {}
        return (lt.get("effect") == "custom" or bool(lt.get("keys"))
                or str(lt.get("color", "rainbow")).lower() not in ("rainbow", *PRESET_COLOURS))

    def apply_lighting(self, kb: Keyboard):
        lt = self.lighting
        bright, speed = int(lt.get("brightness", 9)), int(lt.get("speed", 5))
        colour = lt.get("color") or "rainbow"
        if self.uses_custom_colours():
            base = parse_colour("ffffff" if colour == "rainbow" else colour)
            cols = {k["index"]: base for k in self.keys}
            for kid, c in lt.get("keys", {}).items():
                cols[self.key(kid)["index"]] = parse_colour(c)
            kb.set_custom_colours(cols, bright)
            return
        table = effects(self.model, kb.info.firmware)
        eff = table.get(lt.get("effect", "static"))
        if eff is None:
            raise ValueError(f"unknown effect {lt.get('effect')!r}; choose from: {', '.join(table)}")
        code = 0 if colour == "rainbow" else list(PRESET_COLOURS).index(colour.lower()) + 1
        kb.set_effect(eff["mode"], speed, bright, code)

    def describe(self, layer: str, kid: str) -> Target | None:
        t = self.layers[layer].get(kid)
        return find_target(t) if t else None
