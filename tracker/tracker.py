import ctypes
import ctypes.wintypes
import io
import os
import sys
import time
import threading
from datetime import datetime

import requests
from PIL import ImageGrab

from config import (
    SERVER_URL,
    SCREENSHOT_INTERVAL,
    ACTIVITY_POLL_INTERVAL,
    HEARTBEAT_INTERVAL,
    IDLE_THRESHOLD,
)


class EditorTracker:
    def __init__(self, editor_name: str, editor_id: str = None):
        self.editor_name = editor_name
        self.editor_id = editor_id
        self.running = False
        self.current_app = None
        self.current_window = None
        self.current_start = None
        self.last_input_time = time.time()

    def register(self):
        if self.editor_id:
            return
        try:
            resp = requests.post(
                f"{SERVER_URL}/api/register",
                data={"name": self.editor_name},
                timeout=10,
            )
            data = resp.json()
            self.editor_id = data["editor_id"]
            self._save_id()
            print(f"Registered as {self.editor_name} (ID: {self.editor_id})")
        except Exception as e:
            print(f"Failed to register: {e}")
            sys.exit(1)

    def _save_id(self):
        config_dir = os.path.join(os.getenv("APPDATA", "."), "EditorTracker")
        os.makedirs(config_dir, exist_ok=True)
        with open(os.path.join(config_dir, "editor_id.txt"), "w") as f:
            f.write(self.editor_id)

    @staticmethod
    def _load_id():
        config_dir = os.path.join(os.getenv("APPDATA", "."), "EditorTracker")
        id_file = os.path.join(config_dir, "editor_id.txt")
        if os.path.exists(id_file):
            with open(id_file) as f:
                return f.read().strip()
        return None

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
            requests.post(
                f"{SERVER_URL}/api/activity",
                data={
                    "editor_id": self.editor_id,
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
                requests.post(
                    f"{SERVER_URL}/api/heartbeat",
                    data={"editor_id": self.editor_id},
                    timeout=10,
                )
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

                requests.post(
                    f"{SERVER_URL}/api/screenshot",
                    data={"editor_id": self.editor_id},
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

    def start(self):
        self.register()
        self.running = True
        print(f"Tracker started for {self.editor_name}")
        print("Tracking active apps, idle time, and screenshots...")
        print("Press Ctrl+C to stop.")

        threads = [
            threading.Thread(target=self._track_activity, daemon=True),
            threading.Thread(target=self._send_heartbeat, daemon=True),
            threading.Thread(target=self._take_screenshot, daemon=True),
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
            print("\nTracker stopped.")


def main():
    saved_id = EditorTracker._load_id()

    if saved_id:
        name = input("Enter your name: ").strip()
        print(f"Using saved editor ID: {saved_id}")
        tracker = EditorTracker(name, editor_id=saved_id)
    else:
        name = input("Enter your name (first time setup): ").strip()
        tracker = EditorTracker(name)

    tracker.start()


if __name__ == "__main__":
    main()
