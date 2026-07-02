import os
import uuid
import json
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_db
from auth import is_valid_session, COOKIE_NAME
from console_api import router as console_auth_router, protected as console_router

app = FastAPI(title="Editor Tracker Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "screenshots")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

init_db()

app.include_router(console_auth_router)
app.include_router(console_router)


@app.get("/")
def console_page(request: Request):
    if not is_valid_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/login")
    return FileResponse(os.path.join(STATIC_DIR, "console.html"))


@app.get("/login")
def login_page(request: Request):
    if is_valid_session(request.cookies.get(COOKIE_NAME)):
        return RedirectResponse("/")
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.post("/api/register")
def register_editor(name: str = Form(...)):
    editor_id = str(uuid.uuid4())[:8]
    db = get_db()
    db.execute(
        "INSERT INTO editors (id, name, last_seen, status) VALUES (?, ?, ?, ?)",
        (editor_id, name, datetime.utcnow().isoformat(), "online"),
    )
    db.commit()
    db.close()
    return {"editor_id": editor_id, "name": name}


@app.post("/api/heartbeat")
def heartbeat(editor_id: str = Form(...)):
    db = get_db()
    db.execute(
        "UPDATE editors SET last_seen = ?, status = 'online' WHERE id = ?",
        (datetime.utcnow().isoformat(), editor_id),
    )
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/api/activity")
def log_activity(
    editor_id: str = Form(...),
    app_name: str = Form(...),
    window_title: str = Form(""),
    start_time: str = Form(...),
    duration_seconds: int = Form(0),
    is_idle: int = Form(0),
):
    db = get_db()
    db.execute(
        "INSERT INTO activity_logs (editor_id, app_name, window_title, start_time, duration_seconds, is_idle) VALUES (?, ?, ?, ?, ?, ?)",
        (editor_id, app_name, window_title, start_time, duration_seconds, is_idle),
    )
    db.execute(
        "UPDATE editors SET last_seen = ?, status = 'online' WHERE id = ?",
        (datetime.utcnow().isoformat(), editor_id),
    )
    db.commit()
    db.close()
    return {"status": "ok"}


@app.post("/api/screenshot")
async def upload_screenshot(
    editor_id: str = Form(...),
    file: UploadFile = File(...),
):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{editor_id}_{timestamp}.jpg"
    filepath = os.path.join(SCREENSHOT_DIR, filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    db = get_db()
    db.execute(
        "INSERT INTO screenshots (editor_id, timestamp, filename) VALUES (?, ?, ?)",
        (editor_id, datetime.utcnow().isoformat(), filename),
    )
    db.execute(
        "UPDATE editors SET last_seen = ?, status = 'online' WHERE id = ?",
        (datetime.utcnow().isoformat(), editor_id),
    )
    db.commit()
    db.close()
    return {"status": "ok", "filename": filename}


@app.get("/api/screenshot/{filename}")
def get_screenshot(filename: str):
    filepath = os.path.join(SCREENSHOT_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(filepath, media_type="image/jpeg")


@app.get("/api/editors")
def list_editors():
    db = get_db()
    cutoff = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
    db.execute("UPDATE editors SET status = 'offline' WHERE last_seen < ?", (cutoff,))
    db.commit()

    rows = db.execute("SELECT * FROM editors ORDER BY name").fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.get("/api/editors/{editor_id}/activity")
def get_editor_activity(editor_id: str, date: str = None):
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute(
        "SELECT app_name, window_title, start_time, duration_seconds, is_idle FROM activity_logs WHERE editor_id = ? AND start_time LIKE ? ORDER BY start_time DESC",
        (editor_id, f"{date}%"),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


@app.get("/api/editors/{editor_id}/summary")
def get_editor_summary(editor_id: str, date: str = None):
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")

    db = get_db()
    rows = db.execute(
        "SELECT app_name, SUM(duration_seconds) as total_seconds, is_idle FROM activity_logs WHERE editor_id = ? AND start_time LIKE ? GROUP BY app_name, is_idle ORDER BY total_seconds DESC",
        (editor_id, f"{date}%"),
    ).fetchall()

    total_active = sum(r["total_seconds"] for r in rows if not r["is_idle"])
    total_idle = sum(r["total_seconds"] for r in rows if r["is_idle"])

    apps = {}
    for r in rows:
        if not r["is_idle"]:
            apps[r["app_name"]] = r["total_seconds"]

    db.close()
    return {
        "total_active_seconds": total_active,
        "total_idle_seconds": total_idle,
        "apps": apps,
    }


@app.get("/api/editors/{editor_id}/screenshots")
def get_editor_screenshots(editor_id: str, limit: int = 20):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM screenshots WHERE editor_id = ? ORDER BY timestamp DESC LIMIT ?",
        (editor_id, limit),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
