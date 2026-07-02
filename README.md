# Editor Tracker + Studio Console

A real-time tracking system for video editors, plus a web dashboard (**Studio Console**) to run the whole agency: tasks per client, an income/expense ledger in ₹, and attendance derived automatically from tracker activity.

## Architecture

```
[Editor's Laptop]          [Your Server (VPS)]         [Your Browser / Machine]
 tracker.py  ──────────►   server/main.py   ◄──────── Studio Console (web, /)
 (Windows)                 (FastAPI + SQLite)  ◄────── dashboard.py (Desktop GUI)
```

## Studio Console

Open `http://YOUR_SERVER_IP:8000/` in a browser and sign in with the admin
password. Four tabs:

- **Overview** — who's present today, tasks in motion, overdue count, this month's net
- **Tasks** — grouped by client → project, with assignee, status, priority, due date and a footage/asset link. Overdue tasks are flagged automatically
- **Expenses** — income + expense ledger with monthly summary, a 6-month chart, recurring expenses (weekly/monthly/yearly auto-repeat) and invoice status (Draft → Sent → Paid, overdue flagged)
- **Team** — attendance read automatically from tracker activity: first/last seen, active vs idle time, and a 14-day presence grid. No clock-in needed

### Admin password

Set it once when starting the server (defaults to `studio123` — change it):

```bash
ADMIN_PASSWORD=your-secret-here python main.py
```

An editor counts as **present** after 60 minutes of active (non-idle) tracker
time in a day. Override with `PRESENT_THRESHOLD_MIN=45`.

The database is seeded with a few example clients, editors, tasks and ledger
entries on first run so the console isn't empty — delete them from the UI and
add your real ones.

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
