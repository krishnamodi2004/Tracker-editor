import ctypes
import ctypes.wintypes
import io
import json
import os
import shutil
import subprocess
import sys
import time
import threading
from datetime import datetime

import requests
from PIL import ImageGrab

from config import (
    SERVER_URL,
    VERSION,
    PLACEHOLDER_TOKEN,
    TOKEN_MARKER,
    SCREENSHOT_INTERVAL,
    ACTIVITY_POLL_INTERVAL,
    HEARTBEAT_INTERVAL,
    IDLE_THRESHOLD,
    UPDATE_CHECK_INTERVAL,
)

TRAILER_LEN = len(TOKEN_MARKER) + len(PLACEHOLDER_TOKEN)

APPDATA_DIR = os.path.join(os.getenv("APPDATA", "."), "EditorTracker")
CREDENTIALS_PATH = os.path.join(APPDATA_DIR, "credentials.json")

INSTALL_DIR = os.path.join(os.getenv("LOCALAPPDATA", "."), "EditorTracker")
INSTALL_PATH = os.path.join(INSTALL_DIR, "EditorTracker.exe")
UPDATE_DIR = os.path.join(APPDATA_DIR, "update")


def _load_credentials():
    if os.path.exists(CREDENTIALS_PATH):
        try:
            with open(CREDENTIALS_PATH) as f:
                data = json.load(f)
            if data.get("editor_id") and data.get("token"):
                return data
        except Exception:
            pass
    return None


def _save_credentials(editor_id, token):
    os.makedirs(APPDATA_DIR, exist_ok=True)
    tmp_path = CREDENTIALS_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump({"editor_id": editor_id, "token": token}, f)
    os.replace(tmp_path, CREDENTIALS_PATH)


def _is_running_from(exe_path):
    """Best-effort check for a live process whose image is exe_path. Used to
    avoid duplicate tracking when the install path is locked because another
    instance is already running from it (rather than a transient AV scan)."""
    try:
        import psutil
        target = os.path.normcase(os.path.abspath(exe_path))
        for p in psutil.process_iter(["exe"]):
            try:
                if p.info["exe"] and os.path.normcase(p.info["exe"]) == target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _ensure_installed():
    """Copy a frozen exe to a stable per-user path and relaunch from there, so
    autostart/self-update always target the same file regardless of where the
    editor happened to double-click the installer from."""
    if not getattr(sys, "frozen", False):
        return  # dev mode: `python tracker.py` -- nothing to install
    current = os.path.abspath(sys.executable)
    if os.path.normcase(current) == os.path.normcase(INSTALL_PATH):
        return

    os.makedirs(INSTALL_DIR, exist_ok=True)

    # The install path's exe may be transiently locked (e.g. Defender scanning
    # a just-written file) or genuinely in use by an already-running instance.
    # Retry through the former; on the latter, exit quietly instead of
    # duplicating tracking for the same editor.
    for attempt in range(5):
        try:
            shutil.copy2(current, INSTALL_PATH)
            break
        except PermissionError:
            if _is_running_from(INSTALL_PATH):
                os._exit(0)
            time.sleep(1)
    else:
        return  # still locked with no live instance found -- keep running in place

    subprocess.Popen(
        [INSTALL_PATH],
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os._exit(0)


def _ensure_autostart():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "EditorTracker", 0, winreg.REG_SZ, f'"{INSTALL_PATH}"')
        winreg.CloseKey(key)
    except Exception:
        pass  # non-fatal -- tracker still runs this session even if this fails


def _version_tuple(v):
    return tuple(int(p) for p in v.split("."))


def _read_embedded_token():
    """Reads the invite token from a raw trailer appended after the exe's own
    content (see config.TOKEN_MARKER) -- PyInstaller's onefile archive is
    zlib-compressed, so a token embedded as a plain Python string literal isn't
    found by a byte search, which is why this reads the file directly instead."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        with open(sys.executable, "rb") as f:
            f.seek(-TRAILER_LEN, os.SEEK_END)
            tail = f.read()
        if tail[:len(TOKEN_MARKER)] == TOKEN_MARKER:
            return tail[len(TOKEN_MARKER):].decode("ascii")
    except Exception:
        pass
    return None


class EditorTracker:
    def __init__(self, token: str, editor_id: str = None):
        self.token = token
        self.editor_id = editor_id
        self.running = False
        self.current_app = None
        self.current_window = None
        self.current_start = None
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def activate(self):
        if self.editor_id:
            return
        delay = 5
        while True:
            try:
                resp = self.session.post(
                    f"{SERVER_URL}/api/register",
                    data={"token": self.token},
                    timeout=10,
                )
                if resp.status_code == 200:
                    self.editor_id = resp.json()["editor_id"]
                    _save_credentials(self.editor_id, self.token)
                    return
            except Exception:
                pass
            time.sleep(delay)
            delay = min(delay * 2, 300)

    def _get_active_window(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            window_title = buf.value

            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            import psutil
            try:
                process = psutil.Process(pid.value)
                app_name = process.name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                app_name = "Unknown"

            return app_name, window_title
        except Exception:
            return "Unknown", ""

    def _get_idle_seconds(self):
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwTime", ctypes.c_uint),
            ]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0

    def _send_activity(self, app_name, window_title, start_time, duration, is_idle):
        try:
            self.session.post(
                f"{SERVER_URL}/api/activity",
                data={
                    "app_name": app_name,
                    "window_title": window_title,
                    "start_time": start_time,
                    "duration_seconds": int(duration),
                    "is_idle": 1 if is_idle else 0,
                },
                timeout=10,
            )
        except Exception:
            pass

    def _send_heartbeat(self):
        while self.running:
            try:
                self.session.post(f"{SERVER_URL}/api/heartbeat", timeout=10)
            except Exception:
                pass
            time.sleep(HEARTBEAT_INTERVAL)

    def _take_screenshot(self):
        while self.running:
            try:
                img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=50)
                buf.seek(0)

                self.session.post(
                    f"{SERVER_URL}/api/screenshot",
                    files={"file": ("screenshot.jpg", buf, "image/jpeg")},
                    timeout=30,
                )
            except Exception:
                pass
            time.sleep(SCREENSHOT_INTERVAL)

    def _track_activity(self):
        while self.running:
            app_name, window_title = self._get_active_window()
            idle_secs = self._get_idle_seconds()
            is_idle = idle_secs >= IDLE_THRESHOLD
            now = datetime.utcnow().isoformat()

            if is_idle:
                if self.current_app and self.current_start:
                    duration = (datetime.utcnow() - datetime.fromisoformat(self.current_start)).total_seconds()
                    self._send_activity(self.current_app, self.current_window, self.current_start, duration, False)
                    self.current_app = None

                self._send_activity("IDLE", "", now, ACTIVITY_POLL_INTERVAL, True)
            elif app_name != self.current_app or window_title != self.current_window:
                if self.current_app and self.current_start:
                    duration = (datetime.utcnow() - datetime.fromisoformat(self.current_start)).total_seconds()
                    self._send_activity(self.current_app, self.current_window, self.current_start, duration, False)

                self.current_app = app_name
                self.current_window = window_title
                self.current_start = now

            time.sleep(ACTIVITY_POLL_INTERVAL)

    def _check_for_updates(self):
        while self.running:
            time.sleep(UPDATE_CHECK_INTERVAL)
            try:
                resp = self.session.get(f"{SERVER_URL}/api/version", timeout=10)
                if resp.status_code != 200:
                    continue
                info = resp.json()
                if _version_tuple(info["version"]) <= _version_tuple(VERSION):
                    continue
                self._apply_update(info["download_url"])
            except Exception:
                pass

    def _apply_update(self, download_url):
        if not getattr(sys, "frozen", False):
            return  # dev mode: nothing to self-replace
        try:
            resp = self.session.get(f"{SERVER_URL}{download_url}", stream=True, timeout=60)
            if resp.status_code != 200:
                return
            os.makedirs(UPDATE_DIR, exist_ok=True)
            new_exe = os.path.join(UPDATE_DIR, "EditorTracker-new.exe")
            with open(new_exe, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)

            # A running exe can't overwrite its own file on Windows, so a detached
            # batch script waits for this process to exit before swapping it in.
            bat_path = os.path.join(UPDATE_DIR, "apply_update.bat")
            pid = os.getpid()
            with open(bat_path, "w") as f:
                f.write(
                    "@echo off\r\n"
                    ":wait\r\n"
                    f'tasklist /fi "PID eq {pid}" | find "{pid}" >nul\r\n'
                    "if not errorlevel 1 (\r\n"
                    "  timeout /t 1 /nobreak >nul\r\n"
                    "  goto wait\r\n"
                    ")\r\n"
                    f'move /Y "{new_exe}" "{INSTALL_PATH}"\r\n'
                    f'start "" "{INSTALL_PATH}"\r\n'
                    'del "%~f0"\r\n'
                )
            # stdio must be explicitly redirected, not just inherited -- a detached
            # process with no console leaves cmd.exe's internal "tasklist | find"
            # pipe without valid handles to attach to, which hangs it forever.
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os._exit(0)
        except Exception:
            pass

    def start(self):
        self.activate()
        self.running = True

        threads = [
            threading.Thread(target=self._track_activity, daemon=True),
            threading.Thread(target=self._send_heartbeat, daemon=True),
            threading.Thread(target=self._take_screenshot, daemon=True),
            threading.Thread(target=self._check_for_updates, daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
            if self.current_app and self.current_start:
                duration = (datetime.utcnow() - datetime.fromisoformat(self.current_start)).total_seconds()
                self._send_activity(self.current_app, self.current_window, self.current_start, duration, False)


def main():
    _ensure_installed()
    if getattr(sys, "frozen", False):
        _ensure_autostart()

    creds = _load_credentials()
    if creds:
        tracker = EditorTracker(token=creds["token"], editor_id=creds["editor_id"])
    else:
        token = _read_embedded_token() or PLACEHOLDER_TOKEN
        tracker = EditorTracker(token=token)
    tracker.start()


if __name__ == "__main__":
    main()
