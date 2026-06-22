import io
import time
import threading
from datetime import datetime

import requests
import customtkinter as ctk
from PIL import Image, ImageTk

SERVER_URL = "http://localhost:8000"
REFRESH_INTERVAL = 10  # seconds


class DashboardApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Editor Tracker Dashboard")
        self.geometry("1200x800")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.editors = []
        self.selected_editor = None
        self.screenshot_refs = []

        self._build_ui()
        self._start_refresh()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left panel - editor list
        left = ctk.CTkFrame(self, width=280)
        left.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)
        left.grid_propagate(False)

        ctk.CTkLabel(left, text="Editors", font=("", 20, "bold")).pack(pady=(15, 10))

        self.editor_list_frame = ctk.CTkScrollableFrame(left)
        self.editor_list_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Right panel - details
        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.detail_header = ctk.CTkLabel(right, text="Select an editor", font=("", 22, "bold"))
        self.detail_header.grid(row=0, column=0, sticky="w", padx=20, pady=(15, 5))

        self.detail_status = ctk.CTkLabel(right, text="", font=("", 14))
        self.detail_status.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))

        # Tabview for activity and screenshots
        self.tabs = ctk.CTkTabview(right)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.tab_summary = self.tabs.add("Summary")
        self.tab_activity = self.tabs.add("Activity Log")
        self.tab_screenshots = self.tabs.add("Screenshots")

        # Summary tab
        self.summary_frame = ctk.CTkScrollableFrame(self.tab_summary)
        self.summary_frame.pack(fill="both", expand=True)

        # Activity tab
        self.activity_frame = ctk.CTkScrollableFrame(self.tab_activity)
        self.activity_frame.pack(fill="both", expand=True)

        # Screenshots tab
        self.screenshots_frame = ctk.CTkScrollableFrame(self.tab_screenshots)
        self.screenshots_frame.pack(fill="both", expand=True)

    def _start_refresh(self):
        self._refresh_editors()

    def _refresh_editors(self):
        def fetch():
            try:
                resp = requests.get(f"{SERVER_URL}/api/editors", timeout=10)
                self.editors = resp.json()
            except Exception:
                self.editors = []
            self.after(0, self._update_editor_list)

        threading.Thread(target=fetch, daemon=True).start()

    def _update_editor_list(self):
        for w in self.editor_list_frame.winfo_children():
            w.destroy()

        for editor in self.editors:
            status_color = "#2ecc71" if editor["status"] == "online" else "#e74c3c"
            frame = ctk.CTkFrame(self.editor_list_frame)
            frame.pack(fill="x", pady=3, padx=3)

            status_dot = ctk.CTkLabel(frame, text="●", text_color=status_color, font=("", 16))
            status_dot.pack(side="left", padx=(10, 5))

            name_btn = ctk.CTkButton(
                frame,
                text=editor["name"],
                fg_color="transparent",
                hover_color=("gray70", "gray30"),
                anchor="w",
                command=lambda e=editor: self._select_editor(e),
            )
            name_btn.pack(side="left", fill="x", expand=True)

        self.after(REFRESH_INTERVAL * 1000, self._refresh_editors)

    def _select_editor(self, editor):
        self.selected_editor = editor
        self.detail_header.configure(text=editor["name"])

        status_text = f"Status: {editor['status'].upper()}"
        if editor.get("last_seen"):
            status_text += f"  |  Last seen: {editor['last_seen'][:19]}"
        self.detail_status.configure(
            text=status_text,
            text_color="#2ecc71" if editor["status"] == "online" else "#e74c3c",
        )

        self._load_summary(editor["id"])
        self._load_activity(editor["id"])
        self._load_screenshots(editor["id"])

    def _load_summary(self, editor_id):
        def fetch():
            try:
                resp = requests.get(f"{SERVER_URL}/api/editors/{editor_id}/summary", timeout=10)
                data = resp.json()
            except Exception:
                data = {"total_active_seconds": 0, "total_idle_seconds": 0, "apps": {}}
            self.after(0, lambda: self._render_summary(data))

        threading.Thread(target=fetch, daemon=True).start()

    def _render_summary(self, data):
        for w in self.summary_frame.winfo_children():
            w.destroy()

        active_h = data["total_active_seconds"] / 3600
        idle_h = data["total_idle_seconds"] / 3600

        # Time overview
        time_frame = ctk.CTkFrame(self.summary_frame)
        time_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(time_frame, text="Today's Overview", font=("", 16, "bold")).pack(anchor="w", padx=10, pady=(10, 5))

        stats = ctk.CTkFrame(time_frame, fg_color="transparent")
        stats.pack(fill="x", padx=10, pady=(0, 10))

        for label, value, color in [
            ("Active Time", f"{active_h:.1f}h", "#2ecc71"),
            ("Idle Time", f"{idle_h:.1f}h", "#e67e22"),
            ("Total Time", f"{active_h + idle_h:.1f}h", "#3498db"),
        ]:
            box = ctk.CTkFrame(stats)
            box.pack(side="left", expand=True, fill="x", padx=5)
            ctk.CTkLabel(box, text=value, font=("", 28, "bold"), text_color=color).pack(pady=(10, 0))
            ctk.CTkLabel(box, text=label, font=("", 12)).pack(pady=(0, 10))

        # App breakdown
        if data["apps"]:
            ctk.CTkLabel(self.summary_frame, text="App Usage", font=("", 16, "bold")).pack(anchor="w", padx=20, pady=(10, 5))

            total = max(sum(data["apps"].values()), 1)
            sorted_apps = sorted(data["apps"].items(), key=lambda x: x[1], reverse=True)

            for app_name, seconds in sorted_apps:
                row = ctk.CTkFrame(self.summary_frame)
                row.pack(fill="x", padx=20, pady=2)

                pct = seconds / total
                hours = seconds / 3600

                ctk.CTkLabel(row, text=app_name, font=("", 13), width=200, anchor="w").pack(side="left", padx=(10, 5))
                bar = ctk.CTkProgressBar(row, width=300)
                bar.pack(side="left", padx=5)
                bar.set(pct)
                ctk.CTkLabel(row, text=f"{hours:.1f}h ({pct*100:.0f}%)", font=("", 12)).pack(side="left", padx=5)

    def _load_activity(self, editor_id):
        def fetch():
            try:
                resp = requests.get(f"{SERVER_URL}/api/editors/{editor_id}/activity", timeout=10)
                data = resp.json()
            except Exception:
                data = []
            self.after(0, lambda: self._render_activity(data))

        threading.Thread(target=fetch, daemon=True).start()

    def _render_activity(self, activities):
        for w in self.activity_frame.winfo_children():
            w.destroy()

        if not activities:
            ctk.CTkLabel(self.activity_frame, text="No activity recorded today").pack(pady=20)
            return

        # Header
        header = ctk.CTkFrame(self.activity_frame)
        header.pack(fill="x", padx=5, pady=5)
        for text, width in [("Time", 150), ("App", 200), ("Window", 300), ("Duration", 100)]:
            ctk.CTkLabel(header, text=text, font=("", 12, "bold"), width=width, anchor="w").pack(side="left", padx=5)

        for act in activities[:100]:
            row = ctk.CTkFrame(self.activity_frame, fg_color="transparent")
            row.pack(fill="x", padx=5, pady=1)

            time_str = act["start_time"][11:19] if len(act["start_time"]) > 11 else act["start_time"]
            dur_min = act["duration_seconds"] / 60

            color = "#e67e22" if act["is_idle"] else "white"
            ctk.CTkLabel(row, text=time_str, width=150, anchor="w", text_color=color).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=act["app_name"], width=200, anchor="w", text_color=color).pack(side="left", padx=5)

            title = act.get("window_title", "")
            if len(title) > 40:
                title = title[:40] + "..."
            ctk.CTkLabel(row, text=title, width=300, anchor="w", text_color=color).pack(side="left", padx=5)
            ctk.CTkLabel(row, text=f"{dur_min:.1f}m", width=100, anchor="w", text_color=color).pack(side="left", padx=5)

    def _load_screenshots(self, editor_id):
        def fetch():
            try:
                resp = requests.get(f"{SERVER_URL}/api/editors/{editor_id}/screenshots", timeout=10)
                data = resp.json()
            except Exception:
                data = []
            self.after(0, lambda: self._render_screenshots(data))

        threading.Thread(target=fetch, daemon=True).start()

    def _render_screenshots(self, screenshots):
        for w in self.screenshots_frame.winfo_children():
            w.destroy()
        self.screenshot_refs.clear()

        if not screenshots:
            ctk.CTkLabel(self.screenshots_frame, text="No screenshots yet").pack(pady=20)
            return

        for i, ss in enumerate(screenshots[:20]):
            frame = ctk.CTkFrame(self.screenshots_frame)
            frame.pack(fill="x", padx=10, pady=5)

            ctk.CTkLabel(frame, text=ss["timestamp"][:19], font=("", 12)).pack(anchor="w", padx=10, pady=(5, 0))

            try:
                resp = requests.get(f"{SERVER_URL}/api/screenshot/{ss['filename']}", timeout=10)
                img = Image.open(io.BytesIO(resp.content))
                img.thumbnail((800, 450))
                photo = ctk.CTkImage(light_image=img, size=img.size)
                self.screenshot_refs.append(photo)
                label = ctk.CTkLabel(frame, image=photo, text="")
                label.pack(padx=10, pady=5)
            except Exception:
                ctk.CTkLabel(frame, text="[Failed to load screenshot]").pack(padx=10, pady=5)


def main():
    app = DashboardApp()
    app.mainloop()


if __name__ == "__main__":
    main()
