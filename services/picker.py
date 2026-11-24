"""Explorer-style file and folder pickers for the local desktop session.

The API is loopback-only; a picker therefore runs in a short-lived child process
that owns its own Tk interpreter. It never blocks the API event loop and it never
touches the network. A caller that already knows the path (for example an
automated test or a scripted import) passes it directly and skips the dialog.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

TIMEOUT = 300

SCRIPT = textwrap.dedent(
    """
    import json, sys, tkinter as tk
    from tkinter import filedialog
    mode, title, initial = sys.argv[1], sys.argv[2], sys.argv[3]
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    if mode == "folder":
        value = filedialog.askdirectory(title=title, initialdir=initial or None, mustexist=False)
    else:
        value = filedialog.askopenfilename(title=title, initialdir=initial or None)
    root.destroy()
    print(json.dumps({"path": value or ""}))
    """
)


def choose(mode: str = "folder", title: str = "Choose a folder", initial: str = "") -> dict:
    """Return ``{"path": ...}``; an empty path means the user cancelled."""
    if mode not in {"file", "folder"}:
        raise ValueError("Pick mode must be file or folder.")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", SCRIPT, mode, title, initial or ""],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"The desktop picker could not open: {exc}") from exc
    if completed.returncode:
        detail = (completed.stderr or "").strip().splitlines()
        raise ValueError(
            "The desktop picker is unavailable in this session"
            + (": " + detail[-1] if detail else ".")
        )
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except ValueError as exc:
        raise ValueError("The desktop picker returned no usable path.") from exc
