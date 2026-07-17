"""Admin auth for Studio Console.

Single shared password (ADMIN_PASSWORD env var) and a signed session cookie.
The signing secret is generated once and kept next to the database so sessions
survive server restarts. Tracker endpoints stay unauthenticated — only the
console pages and /api/console/* are gated.
"""
import hmac
import hashlib
import os
import secrets
import time

from fastapi import Request, HTTPException, Header

from database import get_db

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "studio123")
SESSION_DAYS = 30
COOKIE_NAME = "console_session"

_SECRET_PATH = os.path.join(os.path.dirname(__file__), ".console_secret")


def _secret() -> bytes:
    if not os.path.exists(_SECRET_PATH):
        with open(_SECRET_PATH, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(_SECRET_PATH, 0o600)
    with open(_SECRET_PATH) as f:
        return f.read().strip().encode()


def _sign(expiry: str) -> str:
    return hmac.new(_secret(), expiry.encode(), hashlib.sha256).hexdigest()


def make_session_token() -> str:
    expiry = str(int(time.time()) + SESSION_DAYS * 86400)
    return f"{expiry}.{_sign(expiry)}"


def check_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())


def is_valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expiry, sig = token.split(".", 1)
    if not expiry.isdigit() or int(expiry) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expiry))


def require_admin(request: Request):
    if not is_valid_session(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(status_code=401, detail="Not authenticated")


def require_editor(authorization: str | None = Header(None)) -> str:
    """Validates 'Authorization: Bearer <invite token>' and returns the bound editor_id.

    Tracker-facing endpoints (heartbeat/activity/screenshot) use this instead of
    trusting a client-supplied editor_id in the form body.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization[len("Bearer "):].strip()
    db = get_db()
    row = db.execute(
        "SELECT editor_id FROM invites WHERE token = ? AND status = 'activated'", (token,)
    ).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid or inactive token")
    return row["editor_id"]
