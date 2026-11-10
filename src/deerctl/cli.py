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
from .protocol import LAYERS, MODELS, Keyboard, Model, actuation_mode

UDEV_RULE = ('# Drunkdeer keyboards: let the logged-in user reach the config interface\n'
             '# (used by deerctl and by WebHID in Chrome/Edge).\n'
             'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="352d", TAG+="uaccess", MODE="0660"\n')
UDEV_PATH = "/etc/udev/rules.d/70-drunkdeer.rules"


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
        print(f"Rapid Trigger: {'on' if i.rapid_trigger else 'off'}   Turbo: {'on' if i.turbo else 'off'}")
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


def cmd_install_udev(a):
    if not sys.platform.startswith("linux"):
        print("Not needed on this OS.")
        return
    if os.geteuid() != 0:
        print('Run with sudo:  sudo "$(command -v deerctl)" install-udev\n\nOr do it by hand:')
        print(f"  echo '{UDEV_RULE.splitlines()[-1]}' | sudo tee {UDEV_PATH}")
        print("  sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw")
        sys.exit(1)
    Path(UDEV_PATH).write_text(UDEV_RULE)
    subprocess.run(["udevadm", "control", "--reload"], check=False)
    subprocess.run(["udevadm", "trigger", "--subsystem-match=hidraw"], check=False)
    print(f"Installed {UDEV_PATH}. Replug the keyboard if it still isn't accessible.")


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
    sub.add_parser("install-udev", help="(Linux) grant your user access to the keyboard").set_defaults(fn=cmd_install_udev)
    s = sub.add_parser("factory-reset", help="reset the keyboard to factory settings")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_factory_reset)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except (DeviceError, KeyError, ValueError) as e:
        msg = e.args[0] if isinstance(e, KeyError) and e.args else e
        print(f"error: {msg}", file=sys.stderr)
        sys.exit(1)
