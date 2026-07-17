"""Builds the tracker template exe used by the server's /download/{token} route.

Run from a venv with requirements-tracker.txt and requirements-tracker-build.txt
installed:

    python tracker/build.py

Produces server/build/EditorTracker.exe with the placeholder trailer appended,
ready for the server to personalize per invite (see server/main.py).
"""
import os
import subprocess
import sys

TRACKER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TRACKER_DIR)
DIST_DIR = os.path.join(REPO_ROOT, "server", "build")
WORK_DIR = os.path.join(TRACKER_DIR, "build_tmp")
EXE_PATH = os.path.join(DIST_DIR, "EditorTracker.exe")

sys.path.insert(0, TRACKER_DIR)
from config import PLACEHOLDER_TOKEN, TOKEN_MARKER  # noqa: E402


def main():
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onefile", "--noconsole", "--noupx",
            "--name", "EditorTracker",
            "--distpath", DIST_DIR,
            "--workpath", WORK_DIR,
            "--specpath", WORK_DIR,
            os.path.join(TRACKER_DIR, "tracker.py"),
        ],
        check=True,
    )

    with open(EXE_PATH, "ab") as f:
        f.write(TOKEN_MARKER + PLACEHOLDER_TOKEN.encode("ascii"))

    print(f"Built {EXE_PATH} with placeholder trailer appended.")


if __name__ == "__main__":
    main()
