# Editor Tracker

A real-time tracking system for video editors. Monitors active applications, idle time, and captures periodic screenshots. View everything on a live dashboard.

## Architecture

```
[Editor's Laptop]          [Your Server (VPS)]         [Your Machine]
 tracker.py  ──────────►   server/main.py   ◄──────── dashboard.py
 (Windows)                 (FastAPI + SQLite)          (Desktop GUI)
```

## Setup

### 1. Server (run on a VPS or machine with a public IP)

```bash
pip install -r requirements-server.txt
cd server
python main.py
```

The server runs on port **8000** by default.

### 2. Tracker Client (run on each editor's Windows laptop)

1. Edit `tracker/config.py` and set `SERVER_URL` to your server's public address:
   ```python
   SERVER_URL = "http://YOUR_SERVER_IP:8000"
   ```

2. Install and run:
   ```bash
   pip install -r requirements-tracker.txt
   cd tracker
   python tracker.py
   ```

3. On first run, the editor enters their name. A unique ID is saved locally for future sessions.

### 3. Dashboard (run on your machine)

1. Edit `dashboard/dashboard.py` and set `SERVER_URL` to your server's address:
   ```python
   SERVER_URL = "http://YOUR_SERVER_IP:8000"
   ```

2. Install and run:
   ```bash
   pip install -r requirements-dashboard.txt
   cd dashboard
   python dashboard.py
   ```

## Features

- **Active App Tracking** – Logs which application is in the foreground and for how long
- **Idle Detection** – Detects when the editor is AFK (2 min threshold)
- **Screenshots** – Captures the screen every 5 minutes, viewable in the dashboard
- **Real-time Dashboard** – See all editors' status, app usage breakdown, activity log, and screenshots
- **Auto-reconnect** – Tracker keeps working even if the server is temporarily unreachable

## Configuration

Edit `tracker/config.py` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `SCREENSHOT_INTERVAL` | 300s (5 min) | How often to take screenshots |
| `ACTIVITY_POLL_INTERVAL` | 5s | How often to check the active window |
| `IDLE_THRESHOLD` | 120s (2 min) | Time before marking as idle |
| `HEARTBEAT_INTERVAL` | 30s | How often to ping the server |

## Security Notes

- Run the server behind a reverse proxy (nginx) with HTTPS in production
- Consider adding API key authentication for production use
- Screenshots are stored on the server filesystem in `server/screenshots/`
