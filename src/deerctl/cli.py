"""deerctl command line."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .hidio import DeviceError, find_device, list_devices
from .keys import TARGETS
from .profile import Profile
from .protocol import LAYERS, MODELS, PRESET_COLOURS, Keyboard, Model, actuation_mode, effects



def connect() -> Keyboard:
    kb = Keyboard(find_device())
    kb.dev.open()
    kb.identify()
    return kb


def cmd_info(a):
    devs = list_devices()
    if not devs:
        raise DeviceError("No Drunkdeer keyboard found.")
    with find_device() as dev:
        kb = Keyboard(dev)
        i = kb.identify()
        m = kb.model
        mode = actuation_mode(m.ktype, i.firmware)
        print(f"Keyboard:      {dev.name}  ({dev.vid:04x}:{dev.pid:04x}, {dev.path})")
        print(f"Model:         {m.name}  (identity {i.identity})")
        print(f"Firmware:      {i.firmware_str}")
        print(f"Rapid Trigger: {'on' if i.rapid_trigger else 'off'}   Turbo: {'on' if i.turbo else 'off'}"
              + ("  (Turbo locks lighting to static)" if i.turbo else ""))
        print(f"Actuation:     {mode[0]} encoding, 0.2–{mode[4]} mm")
        print(f"Profile file:  {Profile.load(m).path}")


def cmd_layout(a):
    model = _model(a)
    prof = Profile(model)
    rows: dict[int, list] = {}
    for k in prof.keys:
        rows.setdefault(k["row"], []).append(k["id"])
    print(f"{model.name} physical key ids:\n")
    for r in sorted(rows):
        print("  " + "  ".join(rows[r]))


def cmd_keys(a):
    groups: dict[str, list] = {}
    for t in TARGETS.values():
        groups.setdefault(t.group, []).append(t.name)
    for g, names in groups.items():
        print(f"{g}:\n  " + " ".join(names))
    print("\nAlso: hid:<usage> for any raw HID keyboard usage, e.g. hid:0x46")


def cmd_show(a):
    model = _model(a)
    prof = Profile.load(model)
    empty = True
    for layer in LAYERS:
        if prof.layers[layer]:
            empty = False
            print(f"[{layer}]")
            for k, t in sorted(prof.layers[layer].items()):
                print(f"  {k:>14} -> {t}")
    if prof.actuation:
        print(f"[actuation] {prof.actuation}")
        empty = False
    if prof.rapid_trigger:
        print(f"[rapid_trigger] {prof.rapid_trigger}")
        empty = False
    if prof.turbo is not None:
        print(f"[turbo] {'on' if prof.turbo else 'off'}")
        empty = False
    if prof.lighting:
        print(f"[lighting] {prof.lighting}")
        empty = False
    if empty:
        print("No remaps — keyboard uses its defaults.")
    print(f"\n({prof.path})")


def _model(a) -> Model:
    if getattr(a, "model", None):
        return Model.by_name(a.model)
    with find_device() as dev:
        kb = Keyboard(dev)
        kb.identify()
        return kb.model


def _edit_and_apply(a, edit):
    kb = connect()
    try:
        prof = Profile.load(kb.model)
        edit(prof)
        if not a.no_apply:
            prof.apply(kb, progress=lambda s: print(f"  writing {s}…"))
        prof.save()
        print("Saved." if a.no_apply else "Applied and saved.")
    finally:
        kb.dev.close()


def cmd_map(a):
    def edit(p: Profile):
        for pair in a.pairs:
            if "=" not in pair:
                raise SystemExit(f"expected KEY=TARGET, got {pair!r}")
            k, t = pair.split("=", 1)
            p.set(a.layer, k, t)
            print(f"  {a.layer}: {k} → {t}")
    _edit_and_apply(a, edit)


def cmd_unmap(a):
    def edit(p: Profile):
        for k in a.keys:
            p.set(a.layer, k, None)
    _edit_and_apply(a, edit)


def cmd_reset_keymap(a):
    def edit(p: Profile):
        for l in LAYERS:
            p.layers[l].clear()
    _edit_and_apply(a, edit)


def cmd_actuation(a):
    def edit(p: Profile):
        sec = p.actuation or {"default": 2.0, "keys": {}}
        if a.keys:
            for k in a.keys.split(","):
                sec.setdefault("keys", {})[p.key(k.strip())["id"]] = a.mm
        else:
            sec = {"default": a.mm, "keys": {}}
        p.actuation = sec
    _edit_and_apply(a, edit)


def cmd_rt(a):
    def edit(p: Profile):
        rt = p.rapid_trigger or {"enabled": False, "press": 0.3, "release": 0.3, "keys": {}}
        if a.state:
            rt["enabled"] = a.state == "on"
        if a.press is not None:
            rt["press"] = a.press
        if a.release is not None:
            rt["release"] = a.release
        p.rapid_trigger = rt
    _edit_and_apply(a, edit)


def cmd_light(a):
    if a.list:
        with find_device() as dev:
            kb = Keyboard(dev)
            kb.identify()
            print("Effects:", " ".join(effects(kb.model, kb.info.firmware)), "custom")
            print("Colours: rainbow", " ".join(PRESET_COLOURS), "or #rrggbb")
        return

    def edit(p: Profile):
        lt = p.lighting or {"effect": "static", "color": "rainbow", "brightness": 9, "speed": 5}
        if a.effect:
            lt["effect"] = a.effect
        if a.color:
            lt["color"] = a.color
        if a.brightness is not None:
            lt["brightness"] = a.brightness
        if a.speed is not None:
            lt["speed"] = a.speed
        if a.clear_keys:
            lt.pop("keys", None)
        for pair in a.key or []:
            k, _, c = pair.partition("=")
            lt.setdefault("keys", {})[p.key(k)["id"]] = c
        if lt.get("keys") and lt.get("effect") != "custom":
            lt["effect"] = "custom"
        p.lighting = lt
    _edit_and_apply(a, edit)


def cmd_turbo(a):
    def edit(p: Profile):
        p.turbo = a.state == "on"
        if p.turbo and p.lighting:
            print("  note: Turbo locks lighting to static, so the profile's lighting section is set aside.")
            p.lighting = None
    _edit_and_apply(a, edit)


def cmd_apply(a):
    kb = connect()
    try:
        prof = Profile.load(kb.model, Path(a.file) if a.file else None)
        prof.apply(kb, progress=lambda s: print(f"  writing {s}…"))
        if a.file:
            prof.save(Profile(kb.model).path)
        print("Applied.")
    finally:
        kb.dev.close()


def cmd_export(a):
    model = _model(a)
    prof = Profile.load(model)
    prof.save(Path(a.file))
    print(f"Wrote {a.file}")


def cmd_gui(a):
    from .gui import serve
    serve(port=a.port, open_browser=not a.no_browser)


def cmd_setup(a):
    from .system import setup
    setup(a)


def cmd_uninstall(a):
    from .system import uninstall
    uninstall(a)


def cmd_factory_reset(a):
    if not a.yes:
        ans = input("Factory-reset the keyboard (keymap, lighting, actuation)? [y/N] ")
        if ans.lower() != "y":
            return
    kb = connect()
    try:
        kb.factory_reset()
        print("Reset sent.")
    finally:
        kb.dev.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="deerctl", description="Configure Drunkdeer keyboards on Linux & macOS.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="show connected keyboard").set_defaults(fn=cmd_info)
    s = sub.add_parser("layout", help="print the physical key ids for your keyboard")
    s.add_argument("--model", choices=[m["name"] for m in MODELS])
    s.set_defaults(fn=cmd_layout)
    sub.add_parser("keys", help="list everything a key can be mapped to").set_defaults(fn=cmd_keys)
    s = sub.add_parser("show", help="show current profile")
    s.add_argument("--model", choices=[m["name"] for m in MODELS])
    s.set_defaults(fn=cmd_show)

    def layer_opts(s):
        s.add_argument("-l", "--layer", choices=list(LAYERS), default="base",
                       help="base (default), fn1 (held Fn) or fn2")
        s.add_argument("--no-apply", action="store_true", help="only edit the profile file")

    s = sub.add_parser("map", help="remap keys:  deerctl map capslock=lctrl ralt=menu")
    s.add_argument("pairs", nargs="+", metavar="KEY=TARGET")
    layer_opts(s)
    s.set_defaults(fn=cmd_map)
    s = sub.add_parser("unmap", help="restore keys to default")
    s.add_argument("keys", nargs="+")
    layer_opts(s)
    s.set_defaults(fn=cmd_unmap)
    s = sub.add_parser("reset-keymap", help="clear all remaps on all layers")
    s.add_argument("--no-apply", action="store_true")
    s.set_defaults(fn=cmd_reset_keymap)

    s = sub.add_parser("actuation", help="set actuation point in mm (all keys or --keys)")
    s.add_argument("mm", type=float)
    s.add_argument("--keys", help="comma separated key ids, e.g. w,a,s,d")
    s.add_argument("--no-apply", action="store_true")
    s.set_defaults(fn=cmd_actuation)
    s = sub.add_parser("rt", help="rapid trigger:  deerctl rt on --press 0.2 --release 0.2")
    s.add_argument("state", nargs="?", choices=["on", "off"])
    s.add_argument("--press", type=float, help="re-trigger distance (mm)")
    s.add_argument("--release", type=float, help="reset distance (mm)")
    s.add_argument("--no-apply", action="store_true")
    s.set_defaults(fn=cmd_rt)

    s = sub.add_parser("turbo", help="Turbo mode (lower latency; locks lighting to static)")
    s.add_argument("state", choices=["on", "off"])
    s.add_argument("--no-apply", action="store_true")
    s.set_defaults(fn=cmd_turbo)

    s = sub.add_parser("light", help="lighting:  deerctl light breath --color cyan --brightness 6")
    s.add_argument("effect", nargs="?", help="effect name, 'custom' or 'off' (see --list)")
    s.add_argument("-c", "--color", help="rainbow, red, green, blue, yellow, purple, cyan, white or #rrggbb")
    s.add_argument("-b", "--brightness", type=int, choices=range(10), metavar="0-9")
    s.add_argument("-s", "--speed", type=int, choices=range(10), metavar="0-9")
    s.add_argument("-k", "--key", action="append", metavar="KEY=COLOUR",
                   help="per-key colour (switches to custom), repeatable")
    s.add_argument("--clear-keys", action="store_true", help="drop per-key colours")
    s.add_argument("--list", action="store_true", help="list effects for your keyboard")
    s.add_argument("--no-apply", action="store_true")
    s.set_defaults(fn=cmd_light)

    s = sub.add_parser("apply", help="write the profile (or a given JSON file) to the keyboard")
    s.add_argument("file", nargs="?")
    s.set_defaults(fn=cmd_apply)
    s = sub.add_parser("export", help="copy the profile to a file")
    s.add_argument("file")
    s.add_argument("--model", choices=[m["name"] for m in MODELS])
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("gui", help="open the graphical editor in your browser")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_gui)
    sub.add_parser("setup", help="one-time setup: let your user access the keyboard (Linux, asks for sudo)").set_defaults(fn=cmd_setup)
    s = sub.add_parser("uninstall", help="remove the udev rule and installed files (profiles kept unless --purge)")
    s.add_argument("--purge", action="store_true", help="also delete your saved profiles")
    s.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    s.set_defaults(fn=cmd_uninstall)
    s = sub.add_parser("factory-reset", help="reset the keyboard to factory settings")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_factory_reset)

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["install-udev"]:          # old name
        argv[0] = "setup"
    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (DeviceError, KeyError, ValueError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)
