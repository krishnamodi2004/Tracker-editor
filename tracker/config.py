SERVER_URL = "http://localhost:8000"  # set to the production HTTPS domain before each release build

VERSION = "1.0.0"
PLACEHOLDER_TOKEN = "0" * 64  # must stay a 64-char literal -- server substitutes the real invite token in-place

# The built exe has TOKEN_MARKER + a 64-char token appended as a raw trailer after
# PyInstaller's own archive (which is zlib-compressed, so a token embedded as an
# ordinary Python string literal isn't found by a plain byte search). tracker.py
# reads this trailer directly from its own exe file; server/main.py's /download
# route rewrites just those last 64 bytes per invite. Keep this in sync with the
# TOKEN_MARKER constant in server/main.py.
TOKEN_MARKER = b"EDITORTRACKER_TOKEN_V1:"

SCREENSHOT_INTERVAL = 300  # 5 minutes in seconds
ACTIVITY_POLL_INTERVAL = 5  # check active window every 5 seconds
HEARTBEAT_INTERVAL = 30  # send heartbeat every 30 seconds
IDLE_THRESHOLD = 120  # mark idle after 2 minutes of no input
UPDATE_CHECK_INTERVAL = 3600  # check for a newer build once an hour
