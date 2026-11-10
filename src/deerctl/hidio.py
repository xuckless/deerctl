"""Low-level HID transport to the keyboard's vendor interface (usage page 0xFF00, report id 4).

Linux: talks to /dev/hidraw* directly (no dependencies).
macOS: uses the `hidapi` package (pip install hidapi).
"""
from __future__ import annotations

import glob
import os
import select
import sys
import time

REPORT_ID = 4
PAYLOAD = 63

# (vid, pid or None for any). From the Antler web driver's device filter list.
SUPPORTED = [(0x352D, None), (0x05AC, 0x024F), (0x1A81, 0x2094)]


class DeviceError(RuntimeError):
    pass


def _supported(vid: int, pid: int) -> bool:
    return any(vid == v and (p is None or p == pid) for v, p in SUPPORTED)


class HidDevice:
    def __init__(self, path: str, vid: int, pid: int, name: str):
        self.path, self.vid, self.pid, self.name = path, vid, pid, name

    def __repr__(self):
        return f"<{self.name} {self.vid:04x}:{self.pid:04x} at {self.path}>"

    # implemented by subclasses
    def open(self): ...
    def close(self): ...
    def write(self, payload: bytes): ...
    def read(self, timeout: float) -> bytes | None: ...

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *a):
        self.close()


# ----------------------------------------------------------------------------- Linux
class _LinuxHid(HidDevice):
    fd = None

    def open(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError:
            raise DeviceError(
                f"No permission to open {self.path}.\n"
                "Run the one-time setup:  deerctl setup") from None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def write(self, payload: bytes):
        os.write(self.fd, bytes([REPORT_ID]) + payload)

    def read(self, timeout: float) -> bytes | None:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return None
        data = os.read(self.fd, 64)
        if data and data[0] == REPORT_ID:
            return data[1:]
        return b""  # some other report id; caller keeps waiting


def _linux_devices() -> list[HidDevice]:
    out = []
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = open(os.path.join(node, "device/uevent")).read()
            desc = open(os.path.join(node, "device/report_descriptor"), "rb").read()
        except OSError:
            continue
        info = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        try:
            _bus, vid, pid = (int(x, 16) for x in info.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        # vendor-defined usage page 0xFF00 => the configuration interface
        if _supported(vid, pid) and b"\x06\x00\xff" in desc:
            out.append(_LinuxHid("/dev/" + os.path.basename(node), vid, pid,
                                 info.get("HID_NAME", "Drunkdeer keyboard")))
    return out


# ----------------------------------------------------------------------------- hidapi (macOS)
class _HidapiDevice(HidDevice):
    dev = None

    def open(self):
        import hid
        self.dev = hid.device()
        try:
            self.dev.open_path(self.path)
        except OSError as e:
            raise DeviceError(
                f"Could not open keyboard ({e}).\nOn macOS, allow your terminal under "
                "System Settings → Privacy & Security → Input Monitoring, then retry.") from None
        self.dev.set_nonblocking(False)

    def close(self):
        if self.dev is not None:
            self.dev.close()
            self.dev = None

    def write(self, payload: bytes):
        self.dev.write(bytes([REPORT_ID]) + payload)

    def read(self, timeout: float) -> bytes | None:
        data = bytes(self.dev.read(64, int(timeout * 1000)))
        if not data:
            return None
        if len(data) == 64 and data[0] == REPORT_ID:
            return data[1:]
        return data


def _hidapi_devices() -> list[HidDevice]:
    try:
        import hid
    except ImportError:
        raise DeviceError("The 'hidapi' Python package is required on this OS: pip install hidapi")
    out = []
    for d in hid.enumerate():
        if _supported(d["vendor_id"], d["product_id"]) and d.get("usage_page") == 0xFF00:
            out.append(_HidapiDevice(d["path"], d["vendor_id"], d["product_id"],
                                     d.get("product_string") or "Drunkdeer keyboard"))
    return out


def list_devices() -> list[HidDevice]:
    if sys.platform.startswith("linux"):
        return _linux_devices()
    return _hidapi_devices()


def find_device() -> HidDevice:
    devs = list_devices()
    if not devs:
        raise DeviceError("No Drunkdeer keyboard found. Is it plugged in (by cable)?")
    return devs[0]


def drain(dev: HidDevice):
    """Discard any queued input reports."""
    end = time.monotonic() + 0.05
    while time.monotonic() < end:
        if dev.read(0.01) is None:
            break
