"""Tiny local web UI: `deerctl gui`.

Serves a single page on 127.0.0.1; the page talks to this process, which talks
to the keyboard. Works in any browser (no WebHID needed).
"""
from __future__ import annotations

import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources

from .hidio import DeviceError, find_device
from .keys import BUILTIN, TARGETS, target_from_slot
from .profile import Profile
from .protocol import LAYERS, PRESET_COLOURS, Keyboard, actuation_mode, effects

TOKEN = secrets.token_urlsafe(24)
_lock = threading.Lock()


def _session():
    dev = find_device()
    dev.open()
    kb = Keyboard(dev)
    kb.identify()
    return kb


def state() -> dict:
    try:
        kb = _session()
    except DeviceError as e:
        return {"connected": False, "error": str(e)}
    try:
        m, i = kb.model, kb.info
        prof = Profile.load(m)
        mode = actuation_mode(m.ktype, i.firmware)
        keys = []
        for k in prof.keys:
            d = m.defaults.get(k["index"])
            keys.append({**k, "default": _default_name(d) or ""})
        groups: dict[str, list] = {}
        for t in TARGETS.values():
            groups.setdefault(t.group, []).append({"name": t.name, "label": t.label})
        return {
            "connected": True, "model": m.name, "firmware": i.firmware_str,
            "rapid_trigger_on": bool(i.rapid_trigger),
            "travel": {"mode": mode[0], "ap_max": mode[4], "rt_max": mode[5],
                       "step": 1 / mode[3]},
            "keys": keys, "targets": groups, "labels": {t.name: t.label for t in TARGETS.values()},
            "profile": prof.to_json(), "path": str(prof.path),
            "builtin": BUILTIN.get(m.name, {}),
            "effects": list(effects(m, i.firmware)) + ["custom"],
            "colours": PRESET_COLOURS,
        }
    finally:
        kb.dev.close()


def _default_name(slot):
    if not slot:
        return None
    cmd, a, b = slot[0], slot[1], slot[2]
    for typ, code in ((0, b), (1, a), (2, a), (3, cmd)):
        t = target_from_slot(cmd, code, typ)
        if t and t.slot() == slot:
            return t.name
    return None


def save(data: dict) -> dict:
    kb = _session()
    try:
        prof = Profile(kb.model, data, Profile(kb.model).path)
        prof.validate()
        if data.get("apply", True):
            prof.apply(kb)
        prof.save()
        return {"ok": True}
    finally:
        kb.dev.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "deerctl"

    def log_message(self, *a):
        pass

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        if self.path in ("/", "/index.html"):
            html = resources.files(__package__).joinpath("static/index.html").read_text("utf-8")
            return self._send(200, html.replace("__TOKEN__", TOKEN).encode(), "text/html; charset=utf-8")
        if self.path == "/api/state":
            if self.headers.get("X-Token") != TOKEN:
                return self._send(403, b"forbidden", "text/plain")
            with _lock:
                return self._json(200, state())
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, b"forbidden", "text/plain")
        if self.path != "/api/save":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n))
            with _lock:
                self._json(200, save(data))
        except (DeviceError, KeyError, ValueError) as e:
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            self._json(400, {"ok": False, "error": msg})


def serve(port: int = 0, open_browser: bool = True):
    httpd = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"deerctl GUI running at {url}  (Ctrl+C to quit)")
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
