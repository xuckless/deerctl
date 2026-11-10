"""`deerctl setup` and `deerctl uninstall`: system integration.

setup     Linux: install a udev rule so your user can reach the keyboard
          (asks for sudo only for the two commands that need it).
          macOS: nothing to install; just checks the keyboard is reachable.
uninstall Removes the udev rule and, if deerctl was installed with install.sh,
          the installed files. Profiles are kept unless --purge is given.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .hidio import DeviceError, list_devices

UDEV_PATH = Path(os.environ.get("DEERCTL_UDEV_RULE", "/etc/udev/rules.d/70-drunkdeer.rules"))
UDEV_RULE = ('# Installed by deerctl: let the logged-in user reach Drunkdeer keyboards\n'
             '# (used by deerctl and by WebHID in Chrome/Edge). Remove with `deerctl uninstall`.\n'
             'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="352d", TAG+="uaccess", MODE="0660"\n')
MARKER = ".deerctl-install"   # written by install.sh next to the venv

LINUX = sys.platform.startswith("linux")


def _root(cmd: list[str], data: str | None = None) -> None:
    """Run a command as root, via sudo when we aren't root already."""
    if os.geteuid() != 0:
        if not shutil.which("sudo"):
            raise SystemExit(f"Need root for: {' '.join(cmd)} (sudo not found)")
        cmd = ["sudo", *cmd]
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, input=data, text=True, check=True,
                   stdout=subprocess.DEVNULL if data is not None else None)


def _reload_udev():
    _root(["udevadm", "control", "--reload"])
    _root(["udevadm", "trigger", "--subsystem-match=hidraw", "--action=change"])
    subprocess.run(["udevadm", "settle", "--timeout=5"], check=False)


def _check_access(wait: float = 4.0) -> bool:
    end = time.monotonic() + wait
    while True:
        devs = list_devices()
        if devs and all(os.access(d.path, os.R_OK | os.W_OK) for d in devs):
            print(f"✓ Keyboard reachable: {devs[0].name} ({devs[0].path})")
            return True
        if time.monotonic() > end:
            if not devs:
                print("• No keyboard plugged in right now. That's fine; it'll work once connected.")
            else:
                print("! Rule installed, but access isn't granted yet. Unplug and replug the keyboard.")
            return False
        time.sleep(0.3)


def setup(args) -> None:
    if not LINUX:
        print("Nothing to install on this OS.")
        try:
            if list_devices():
                print("✓ Keyboard found.")
            else:
                print("• No keyboard found right now.")
        except DeviceError as e:
            print(f"! {e}")
        print("If opening the keyboard fails on macOS, allow your terminal under\n"
              "  System Settings → Privacy & Security → Input Monitoring.")
        return
    current = UDEV_PATH.read_text() if UDEV_PATH.exists() else None
    if current == UDEV_RULE:
        print(f"✓ udev rule already installed ({UDEV_PATH})")
    else:
        print(f"Installing udev rule {UDEV_PATH} (needs sudo):")
        _root(["tee", str(UDEV_PATH)], data=UDEV_RULE)
        _root(["chmod", "644", str(UDEV_PATH)])
        _reload_udev()
    _check_access()
    print("\nAll set. Try:  deerctl info   or   deerctl gui")


def _install_dir() -> Path | None:
    """The install.sh-managed directory, if this deerctl came from install.sh."""
    root = Path(sys.prefix).resolve().parent
    return root if (root / MARKER).exists() else None


def uninstall(args) -> None:
    from .profile import config_dir
    home = _install_dir()
    links = []
    if home:
        for line in (home / MARKER).read_text().splitlines():
            p = Path(line.strip())
            if line.strip() and p.is_symlink():
                links.append(p)
    cfg = config_dir()

    plan = []
    if LINUX and UDEV_PATH.exists():
        plan.append(f"remove udev rule      {UDEV_PATH}  (sudo)")
    for l in links:
        plan.append(f"remove command link   {l}")
    if home:
        plan.append(f"remove installation   {home}")
    if args.purge and cfg.exists():
        plan.append(f"delete your profiles  {cfg}")

    print("deerctl uninstall will:")
    for p in plan or ["(nothing to remove)"]:
        print("  • " + p)
    if not args.purge and cfg.exists():
        print(f"  (keeping your profiles in {cfg}; add --purge to delete them)")
    if not home:
        print("  (deerctl wasn't installed with install.sh; remove the package with\n"
              "   `pipx uninstall deerctl` or `pip uninstall deerctl` afterwards)")
    print("Your keyboard keeps its current remaps/lighting. To restore its defaults first, run\n"
          "`deerctl reset-keymap` or `deerctl factory-reset` before uninstalling.")
    if not plan:
        return
    if not args.yes:
        try:
            ok = input("\nProceed? [y/N] ").strip().lower() == "y"
        except EOFError:
            ok = False
        if not ok:
            print("Cancelled.")
            return

    if LINUX and UDEV_PATH.exists():
        _root(["rm", "-f", str(UDEV_PATH)])
        _reload_udev()
    for l in links:
        l.unlink(missing_ok=True)
    if args.purge and cfg.exists():
        shutil.rmtree(cfg)
    if home:
        shutil.rmtree(home)   # safe: the running interpreter is already loaded
    print("✓ deerctl uninstalled.")
