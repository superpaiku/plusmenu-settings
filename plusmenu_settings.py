#!/usr/bin/env python3
"""Plusmenu-Settings: choose which apps the Steam Frame dashboard's + menu lists.

The + menu's "Launch Program" list is SteamClient.Apps.ScanForInstalledNonSteamApps(), the
scan "Add a Non-Steam Game" uses, run by Steam with XDG_CURRENT_DESKTOP=gamescope over the
desktop files in XDG_DATA_HOME/applications and its XDG_DATA_DIRS, the first file of a name
winning. The scan leaves out what GIO wouldn't show in gamescope (NotShowIn, OnlyShowIn,
NoDisplay, Hidden, TryExec), Terminal=true apps and steam:// shortcuts. The dashboard
(steamui sp.js) then drops apps whose executable is steam or vrurlhandler, and, unless
Steam's developer mode is on, DEV_ONLY ones; "Install Chromium" always stays. So a file
whose NotShowIn has gamescope is left out, while KDE (Desktop Mode, the Frametop desktop)
still lists it.

Hiding an app writes that key without touching system files:
  - an app whose file is in ~/.local/share/applications gets it added in place, marked
    X-PlusmenuSettings-Added so showing it again takes it out;
  - any other app gets a copy there, marked X-PlusmenuSettings-Copy, which showing it again deletes.
    With Frametop installed, the copy is made with its ft_apps.standalone(), so the app keeps
    Launch as Standalone in the Frametop desktop (a file in XDG_DATA_HOME wins over Frametop's
    copy, which Frametop then removes).

The apps hidden here are also kept in STATE, so `sync` (run by the systemd units install.sh
adds, whenever an applications folder changes and every hour) can hide an app again whose
entry an install rewrote, redo a copy whose app was updated, and delete one whose app is gone.

  plusmenu-settings                  open the window
  plusmenu-settings list [--hidden]  list the apps (hidden: only the ones hidden here)
  plusmenu-settings hide ID...       hide apps from the dashboard (ID: the desktop file name)
  plusmenu-settings show ID...       show them again
  plusmenu-settings sync             bring the entries of the apps hidden here up to date
"""
import base64
import importlib.util
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import sys
import urllib.request
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

DESKTOP = "gamescope"
GROUP = "[Desktop Entry]"
MARK_COPY = "X-PlusmenuSettings-Copy"
MARK_ADDED = "X-PlusmenuSettings-Added"
MARK_SOURCE = "X-PlusmenuSettings-Source"
FRAMETOP_APPS = os.path.expanduser("~/.local/share/frametop/apps")
FT_APPS_PY = os.path.expanduser("~/frametop/float/ft_apps.py")
# Not XDG_STATE_HOME: the Frametop session points the XDG folders elsewhere, systemd doesn't
STATE = os.environ.get("PLUSMENU_STATE") or os.path.expanduser("~/.local/state/plusmenu-settings/hidden.json")
DEFAULT_DATA_DIRS = ["~/.local/share/flatpak/exports/share", "/var/lib/flatpak/exports/share",
                     "/usr/local/share", "/usr/share"]
# The dashboard's filters on the scan, by executable name (steamui sp.js)
NEVER = ["steam", "vrurlhandler"]
DEV_ONLY = ["firewall-config", "vrurlhandler", "vlc", "dolphin", "cmake-gui", "plasma-discover", "konsole",
            "systemsettings", "qrenderdoc", "sh", "lxterminal"]
ALWAYS = ["Install Chromium"]
SELF_ID = "plusmenu-settings.desktop"  # this app's own entry (install.sh), which it won't hide
STEAM_DEBUG = "http://127.0.0.1:8080/json"


def _steam_eval(expression, timeout=3):
    """The value of a JavaScript expression in the Steam client's SharedJSContext, through its
    local CEF debugging port (on when Steam's developer mode turned it on)."""
    targets = json.load(urllib.request.urlopen(STEAM_DEBUG, timeout=timeout))
    url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("title") == "SharedJSContext")
    host_port, path = url[len("ws://"):].split("/", 1)
    host, port = host_port.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                raise OSError("no handshake")
            buf += chunk
        buf = buf.split(b"\r\n\r\n", 1)[1]
        data = json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": expression, "returnByValue": True}}).encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n))
        s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

        def need(k):
            nonlocal buf
            while len(buf) < k:
                chunk = s.recv(65536)
                if not chunk:
                    raise OSError("connection closed")
                buf += chunk
        while True:
            msg = b""
            while True:
                need(2)
                fin, n, off = buf[0] & 0x80, buf[1] & 127, 2
                if n == 126:
                    need(4)
                    n, off = struct.unpack(">H", buf[2:4])[0], 4
                elif n == 127:
                    need(10)
                    n, off = struct.unpack(">Q", buf[2:10])[0], 10
                need(off + n)
                msg, buf = msg + buf[off:off + n], buf[off + n:]
                if fin:
                    break
            reply = json.loads(msg)
            if reply.get("id") == 1:
                return reply["result"]["result"].get("value")


# Steam's clientSettings store, found among steamui's webpack modules
_DEV_MODE_JS = """(() => {
  const chunk = Object.keys(window).find(k => k.startsWith("webpackChunk"));
  let req; window[chunk].push([[Symbol()], {}, r => { req = r; }]);
  for (const id of Object.keys(req.m)) {
    let m; try { m = req(id); } catch (e) { continue; }
    for (const v of Object.values(m || {}))
      if (v && typeof v === "object" && v.clientSettings && "developer_mode_enabled" in v.clientSettings)
        return !!v.clientSettings.developer_mode_enabled;
  }
  return null;
})()"""
_dev_mode = []


def developer_mode(refresh=False):
    """Whether Steam's developer mode is on, or None when that can't be told."""
    if refresh:
        _dev_mode.clear()
    if not _dev_mode:
        try:
            _dev_mode.append(_steam_eval(_DEV_MODE_JS))
        except (OSError, ValueError, KeyError, StopIteration):
            _dev_mode.append(None)
    return _dev_mode[0]


def _executable(exec_line):
    try:
        args = shlex.split(exec_line or "")
    except ValueError:
        args = (exec_line or "").split()
    return os.path.basename(args[0]) if args else ""


def steam_environ():
    """The environment of the running Steam client, or {} when it isn't running."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "steam":
                    continue
            with open(f"/proc/{pid}/environ", "rb") as f:
                pairs = [p.split(b"=", 1) for p in f.read().split(b"\0") if b"=" in p]
            return {k.decode(errors="replace"): v.decode(errors="replace") for k, v in pairs}
        except OSError:
            continue
    return {}


def search_path():
    """(Steam's XDG_DATA_HOME/applications, its applications folders, home first).
    PLUSMENU_DATA_HOME and PLUSMENU_DATA_DIRS override them (for tests)."""
    env = steam_environ()
    home = (os.environ.get("PLUSMENU_DATA_HOME") or env.get("XDG_DATA_HOME")
            or os.path.expanduser("~/.local/share"))
    dirs = (os.environ.get("PLUSMENU_DATA_DIRS") or env.get("XDG_DATA_DIRS") or "").split(":")
    dirs = [os.path.expanduser(d) for d in dirs if d] or [os.path.expanduser(d) for d in DEFAULT_DATA_DIRS]
    ours = os.path.realpath(FRAMETOP_APPS)
    dirs = [d for d in dirs if os.path.realpath(d) != ours]
    home_apps = os.path.join(home, "applications")
    return home_apps, [home_apps] + [os.path.join(d, "applications") for d in dirs]


# Desktop file text, edited line by line so the rest of a file stays as it was.

def _group_range(lines):
    start = next((i for i, l in enumerate(lines) if l.strip() == GROUP), None)
    if start is None:
        raise ValueError("no [Desktop Entry] group")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    return start, end


def _key_index(lines, key, start, end):
    pat = re.compile(rf"^{re.escape(key)}\s*=")
    return next((i for i in range(start + 1, end) if pat.match(lines[i])), None)


def get_key(text, key):
    lines = text.splitlines(keepends=True)
    start, end = _group_range(lines)
    i = _key_index(lines, key, start, end)
    return None if i is None else lines[i].split("=", 1)[1].strip()


def set_key(text, key, value):
    """The text with key set to value in [Desktop Entry], or removed for value None."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    start, end = _group_range(lines)
    i = _key_index(lines, key, start, end)
    if value is None:
        if i is not None:
            del lines[i]
    elif i is not None:
        lines[i] = f"{key}={value}\n"
    else:
        lines.insert(start + 1, f"{key}={value}\n")
    return "".join(lines)


def _list(value):
    return [v for v in (value or "").split(";") if v]


def with_desktop(text, hidden):
    """The text with gamescope added to or taken out of NotShowIn."""
    values = [v for v in _list(get_key(text, "NotShowIn")) if v != DESKTOP]
    if hidden:
        values.append(DESKTOP)
    return set_key(text, "NotShowIn", ";".join(values) + ";" if values else None)


@dataclass
class App:
    id: str          # desktop file ID, e.g. vlc.desktop
    path: str        # the file Steam reads
    in_home: bool    # whether that's in ~/.local/share/applications
    name: str
    comment: str
    icon: object     # Gio.Icon or None
    state: str       # "shown", "hidden" (by NotShowIn=gamescope) or "system" (hidden otherwise)
    reason: str      # why a "system" app isn't listed
    ours: bool       # whether this app's NotShowIn was written here

    @property
    def shown(self):
        return self.state == "shown"


def _read(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def _write(path, text):
    tmp = path + ".plusmenu-settings.tmp"
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(text)
    os.replace(tmp, path)


def _describe(app_id, path, in_home, dev):
    try:
        text = _read(path)
        if get_key(text, "Type") != "Application":
            return None
    except (OSError, ValueError):
        return None
    ours = get_key(text, MARK_COPY) == "true" or get_key(text, MARK_ADDED) == "true"
    try:
        info = Gio.DesktopAppInfo.new_from_filename(path)
    except TypeError:  # PyGObject raises for the NULL of a Hidden or missing-TryExec file
        info = None
    name = (info.get_display_name() if info else None) or get_key(text, "Name") or app_id
    comment = (info.get_description() if info else None) or ""
    icon = info.get_icon() if info else None
    if DESKTOP in _list(get_key(text, "NotShowIn")):
        state, reason = "hidden", ""
    elif info is None:
        state = "system"
        reason = "Hidden=true" if (get_key(text, "Hidden") or "").lower() == "true" else "program not found (TryExec)"
    elif info.get_nodisplay():
        state, reason = "system", "NoDisplay=true"
    elif not info.get_show_in(DESKTOP):
        state, reason = "system", f"OnlyShowIn={get_key(text, 'OnlyShowIn') or ''}"
    elif (get_key(text, "Terminal") or "").lower() == "true":
        state, reason = "system", "terminal program"
    elif get_key(text, "Name") in ALWAYS:
        state, reason = "shown", ""
    elif _executable(get_key(text, "Exec")) in NEVER:
        state, reason = "system", "Steam shortcut (it's in the library)"
    elif _executable(get_key(text, "Exec")) in DEV_ONLY and dev is False:
        state, reason = "system", "only in Steam developer mode"
    else:
        state, reason = "shown", ""
    return App(app_id, path, in_home, name, comment, icon, state, reason, ours)


def scan(refresh=False):
    """Every app in Steam's search path, as the + menu would see it, sorted by name."""
    dev = developer_mode(refresh)
    home_apps, roots = search_path()
    apps = [_describe(i, p, root == home_apps, dev) for i, (p, root) in _desktop_files(roots).items()]
    return sorted((a for a in apps if a), key=lambda a: (a.name.casefold(), a.id))


def _desktop_files(roots):
    """Desktop file ID -> (its path, its applications folder), the first one found winning."""
    found = {}
    for root in roots:
        for dirpath, _dirs, files in os.walk(root, followlinks=True):
            for name in files:
                if name.endswith(".desktop"):
                    path = os.path.join(dirpath, name)
                    found.setdefault(os.path.relpath(path, root).replace("/", "-"), (path, root))
    return found


def find(app_id):
    app = next((a for a in scan() if a.id == app_id), None)
    if app is None:
        raise LookupError(f"{app_id}: no app by that name")
    return app


def _refresh(home_apps):
    try:
        subprocess.run(["update-desktop-database", "-q", home_apps], check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


def hidden_ids():
    """The IDs of the apps hidden here. Without STATE yet (hidden by an older version), the ones
    whose entry has our marks."""
    try:
        with open(STATE) as f:
            return set(json.load(f))
    except (FileNotFoundError, ValueError, TypeError):
        ids = {a.id for a in scan() if a.state == "hidden" and a.ours}
        _save_hidden(ids)
        return ids


def _save_hidden(ids):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    _write(STATE, json.dumps(sorted(ids), indent=1) + "\n")


_ft_apps = []


def _frametop():
    """Frametop's ft_apps module, or None without Frametop."""
    if not _ft_apps:
        module = None
        if os.path.isfile(FT_APPS_PY):
            try:
                spec = importlib.util.spec_from_file_location("ft_apps", FT_APPS_PY)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if not callable(getattr(module, "standalone", None)):
                    module = None
            except Exception:  # someone else's code: any failure only means no Launch as Standalone
                module = None
        _ft_apps.append(module)
    return _ft_apps[0]


def _copy_text(app_id, source):
    """What our copy of the app with that desktop file holds."""
    text = None
    if _frametop():
        try:
            text = _frametop().standalone(source, app_id)
        except Exception:
            text = None
    if text is None:
        text = _read(source)
    return set_key(set_key(with_desktop(text, True), MARK_COPY, "true"), MARK_SOURCE, source)


def _hide_entry(app):
    if app.in_home:
        text = with_desktop(_read(app.path), True)
        if get_key(text, MARK_COPY) != "true":
            text = set_key(text, MARK_ADDED, "true")
        _write(app.path, text)
    else:
        home_apps, _ = search_path()
        os.makedirs(home_apps, exist_ok=True)
        _write(os.path.join(home_apps, app.id), _copy_text(app.id, app.path))


def hide(app):
    if app.id == SELF_ID:
        raise ValueError(f"{app.id}: Plusmenu-Settings can't hide itself")
    ids = hidden_ids()  # first, so a sync running meanwhile hides it too rather than not at all
    if app.id not in ids:
        _save_hidden(ids | {app.id})
    if app.state == "hidden":
        return
    _hide_entry(app)
    _refresh(search_path()[0])


def show(app):
    ids = hidden_ids()
    if app.id in ids:
        _save_hidden(ids - {app.id})
    if app.state != "hidden":
        return
    home_apps, _ = search_path()
    text = _read(app.path)
    if app.in_home and get_key(text, MARK_COPY) == "true":
        os.remove(app.path)
    else:
        _write(app.path, set_key(with_desktop(text, False), MARK_ADDED, None))
    _refresh(home_apps)


def sync():
    """Bring the entries of the apps hidden here up to date: hide again one whose entry an
    install rewrote, redo a copy whose app's file changed, delete one whose app is gone (it's
    hidden again if the app comes back). Returns what it did, a line each."""
    ids = hidden_ids()
    if not ids:
        return []
    home_apps, roots = search_path()
    apps = {a.id: a for a in scan()}
    sources = _desktop_files(roots[1:])
    done = []
    for app_id in sorted(ids):
        app = apps.get(app_id)
        if app is None or app_id == SELF_ID:
            continue
        try:
            text = _read(app.path) if app.in_home else None
            if text is not None and get_key(text, MARK_COPY) == "true":
                if app_id not in sources:
                    os.remove(app.path)
                    done.append(f"{app_id}: app removed, copy deleted")
                    continue
                want = _copy_text(app_id, sources[app_id][0])
                if text != want:
                    _write(app.path, want)
                    done.append(f"{app_id}: copy updated")
            elif app.state == "shown":
                _hide_entry(app)
                done.append(f"{app_id}: hidden again")
        except (OSError, ValueError) as e:
            done.append(f"{app_id}: {e}")
    if done:
        _refresh(home_apps)
    return done


# Command line

def cli(args):
    cmd = args[0]
    if cmd == "list":
        only_hidden = "--hidden" in args[1:]
        for a in scan():
            if only_hidden and a.state != "hidden":
                continue
            mark = {"shown": "shown", "hidden": "HIDDEN", "system": "never (" + a.reason + ")"}[a.state]
            print(f"{mark:<28} {a.id:<50} {a.name}")
        return 0
    if cmd in ("hide", "show") and len(args) > 1:
        status = 0
        for app_id in args[1:]:
            try:
                app = find(app_id)
                if cmd == "hide" and app.state == "system":
                    print(f"{app_id}: isn't in the dashboard anyway ({app.reason})")
                    continue
                (hide if cmd == "hide" else show)(app)
                print(f"{app_id}: {'hidden' if cmd == 'hide' else 'shown again'}")
            except (LookupError, OSError, ValueError) as e:
                print(e, file=sys.stderr)
                status = 1
        return status
    if cmd == "sync" and len(args) == 1:
        for line in sync():
            print(line)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


# Window: plusmenu_settings.qml, a Kirigami UI run by Qt's qml runtime (SteamOS has no Python
# bindings for Qt), which does everything through a local JSON API served here.

QML = os.path.join(os.path.dirname(os.path.realpath(__file__)), "plusmenu_settings.qml")


def _icon_source(icon):
    """A Gio.Icon as a Kirigami.Icon source: an icon name or a file URL."""
    if isinstance(icon, Gio.ThemedIcon):
        return next(iter(icon.get_names()), "")
    if isinstance(icon, Gio.FileIcon):
        return icon.get_file().get_uri()
    return ""


def _app_json(app):
    if app.id == SELF_ID and app.shown:
        subtitle = f"{app.id} · this app can't hide itself"
    elif app.state == "system":
        subtitle = f"{app.id} · {app.reason}"
    else:
        subtitle = app.id + (" · " + app.comment if app.comment else "")
    return {"appId": app.id, "name": app.name, "subtitle": subtitle, "iconSource": _icon_source(app.icon),
            "status": app.state, "locked": app.state == "system" or (app.id == SELF_ID and app.shown)}


def api(request):
    """The window's request ({"action": load, hide, show or show-all, ...}) done: a message to show,
    if any, and the apps as they now are."""
    action, message = request.get("action"), None
    if action in ("hide", "show"):
        try:
            app = find(request.get("appId"))
            (hide if action == "hide" else show)(app)
            message = f"{app.name} {'hidden' if action == 'hide' else 'is shown again'}"
        except (LookupError, OSError, ValueError) as e:
            message = str(e)
    elif action == "show-all":
        n, errors = 0, []
        for app in scan():
            if app.state == "hidden":
                try:
                    show(app)
                    n += 1
                except (OSError, ValueError) as e:
                    errors.append(f"{app.name}: {e}")
        message = "\n".join(errors + [f"{n} apps shown again"])
    elif action != "load":
        raise ValueError(f"unknown action {action!r}")
    apps = scan(refresh=bool(request.get("refresh")))
    return {"message": message, "dev": developer_mode(), "apps": [_app_json(a) for a in apps]}


def gui():
    import http.server
    import secrets
    import shutil
    import threading

    token = secrets.token_urlsafe(24)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            # The token keeps other local programs and web pages out
            if not secrets.compare_digest(self.headers.get("X-Plusmenu-Token", ""), token):
                return self.send_error(403)
            try:
                request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
                status, reply = 200, api(request)
            except Exception as e:  # shown in the window rather than lost
                status, reply = 500, {"message": f"Error: {e}"}
            body = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    # One request at a time, so a hide and a show never run together
    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    qml = shutil.which("qml6") or "/usr/lib/qt6/bin/qml"
    env = dict(os.environ)
    env.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")  # Breeze outside Plasma too
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        return subprocess.run([qml, "-a", "widget", QML, "--", url, token], env=env).returncode
    except OSError as e:
        print(f"Can't start {qml}: {e}", file=sys.stderr)
        return 1
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(cli(sys.argv[1:]) if len(sys.argv) > 1 else gui())
