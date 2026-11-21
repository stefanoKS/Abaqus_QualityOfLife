"""Run the loopback API and built UI alongside a separate queue worker.

Invoked by ``start-abaqus-qol.cmd`` (double-click) or directly. The launcher is
idempotent:

* a healthy instance already on the port is reused instead of starting a second
  worker, and the browser is pointed at it;
* missing repository-local dependencies and browser build outputs are prepared
  when the prerequisites are installed, with an actionable message otherwise;
* the browser opens only after ``/api/health`` answers, never in test mode.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
PRODUCT = "Abaqus QOL"
DEFAULT_PORT = 8765
LOCK = ROOT / ".local" / "serve.lock"

# Imported by the API, the worker and the engineering package. Every name must
# resolve before the server starts, otherwise the failure is a bare traceback.
REQUIRED_MODULES = "fastapi,uvicorn,pydantic,ezdxf,gmsh,numpy,shapely,psutil,httpx"


def venv_python():
    return ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def in_project_venv():
    """True when this interpreter uses the repository virtual environment.

    ``sys.prefix`` is authoritative: on some Windows installations the venv's
    ``python.exe`` is a shim that relaunches the base image, so comparing
    ``sys.executable`` against the venv path would never match and would
    re-execute forever.
    """
    try:
        return Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    except OSError:
        return False


def run(command, **kwargs):
    print("  " + " ".join(str(part) for part in command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def reexec_inside_venv():
    """Re-run this script with the repository interpreter so imports resolve."""
    if os.environ.get("ABAQUS_QOL_BOOTSTRAP") == "1":
        raise SystemExit(
            f"{PRODUCT}: the repository Python environment did not activate.\n"
            "Delete the .venv folder and run start-abaqus-qol.cmd again."
        )
    python = venv_python()
    if not python.is_file():
        if sys.version_info < (3, 11):
            raise SystemExit(
                f"{PRODUCT}: Python 3.11 or newer is required (found "
                f"{sys.version.split()[0]}).\n"
                "Install a current Python and run start-abaqus-qol.cmd again."
            )
        print(f"{PRODUCT}: creating the local Python environment once…", flush=True)
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    os.environ["ABAQUS_QOL_BOOTSTRAP"] = "1"
    os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])


def ensure_dependencies():
    probe = subprocess.run(
        [sys.executable, "-c", f"import {REQUIRED_MODULES}"],
        cwd=ROOT,
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    print(f"{PRODUCT}: installing the pinned Python dependencies once…", flush=True)
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(ROOT / "requirements.txt"),
        ],
        cwd=ROOT,
    )


def newest(paths):
    latest = 0.0
    for base in paths:
        if base.is_file():
            latest = max(latest, base.stat().st_mtime)
        elif base.is_dir():
            for item in base.rglob("*"):
                if item.is_file():
                    latest = max(latest, item.stat().st_mtime)
    return latest


def ensure_web(rebuild=False):
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit(
            f"{PRODUCT}: the browser build is missing and Node.js is not on PATH.\n"
            "Install Node.js 20 or newer, then run start-abaqus-qol.cmd again."
        )
    if not (WEB / "node_modules").is_dir():
        print(f"{PRODUCT}: installing the browser dependencies once…", flush=True)
        lock = WEB / "package-lock.json"
        run([npm, "ci"] if lock.is_file() else [npm, "install"], cwd=WEB)
    dist = WEB / "dist" / "index.html"
    sources = max(
        newest([WEB / "src", WEB / "assets"]),
        newest([WEB / name for name in ("index.html", "package.json", "vite.config.ts")]),
    )
    if rebuild or not dist.is_file() or dist.stat().st_mtime < sources:
        print(f"{PRODUCT}: building the browser bundle…", flush=True)
        run([npm, "run", "build"], cwd=WEB)


def health(port, timeout=1.0):
    """Return the identity payload when this port already serves Abaqus QOL."""
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=timeout
        ) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    return payload if payload.get("product") == PRODUCT else None


def port_available(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def open_when_ready(port, label):
    for _ in range(240):
        if health(port, timeout=0.5):
            print(f"{PRODUCT} ready at http://127.0.0.1:{port}", flush=True)
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        time.sleep(0.25)
    print(f"{PRODUCT}: {label} did not report ready within 60 s.", flush=True)


def acquire_lock():
    """Return ``True`` when this launch owns the lock, or the owner's details."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            with LOCK.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "port": DEFAULT_PORT}))
            return True
        except FileExistsError:
            try:
                owner = json.loads(LOCK.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                owner = {}
            if health(owner.get("port", DEFAULT_PORT), timeout=0.5):
                return owner
            # A crashed launch left the lock behind; take it over.
            LOCK.unlink(missing_ok=True)
    return None


def store_root():
    from services import store

    return store.root()


def serve(port, test_data=None, browser=True):
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    if not (WEB / "dist/index.html").is_file():
        raise SystemExit(f"{PRODUCT}: build the browser first: npm --prefix apps/web run build")
    if test_data:
        os.environ["SEAL_DATA"] = test_data
        for name in (
            "ABAQUS_QOL_DATA",
            "SIMPLIFY_ABAQUS_LAUNCHER",
            "ABAQUS_QOL_LAUNCHER",
            "SEAL_ODA",
            "ABAQUS_QOL_ODA",
        ):
            os.environ.pop(name, None)
    import uvicorn

    stop = store_root() / ("stop-" + uuid4().hex)
    args = [sys.executable, "-m", "services.worker", "--stop-file", str(stop)]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    worker = subprocess.Popen(args, cwd=ROOT, creationflags=flags)
    if browser:
        threading.Thread(
            target=open_when_ready, args=(port, "the workbench"), daemon=True
        ).start()
    try:
        print(
            f"{PRODUCT} http://127.0.0.1:{port} · worker PID {worker.pid}\n"
            f"  interpreter {sys.executable}",
            flush=True,
        )
        uvicorn.run("services.api.main:app", host="127.0.0.1", port=port, log_level="warning")
    finally:
        stop.touch()
        print("Waiting for the worker to finish its current operation…", flush=True)
        worker.wait()
        stop.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"{PRODUCT} local workbench launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--test-data", action="store_true", help="Temporary isolated database for browser tests"
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the browser bundle first")
    parser.add_argument("--prepare", action="store_true", help="Prepare dependencies and exit")
    args = parser.parse_args(argv)

    if args.test_data:
        # Automated tests supply the interpreter and expect no bootstrap side effects.
        with tempfile.TemporaryDirectory(prefix="seal-browser-") as directory:
            serve(args.port, directory, browser=False)
        return 0

    if not in_project_venv():
        reexec_inside_venv()
        return 0  # Unreachable: os.execv replaces the process.

    ensure_dependencies()
    ensure_web(args.rebuild)
    if args.prepare:
        print(f"{PRODUCT}: environment and browser bundle are ready.", flush=True)
        return 0

    existing = health(args.port)
    if existing:
        print(
            f"{PRODUCT} is already running on http://127.0.0.1:{args.port} "
            f"(PID {existing.get('pid')}). Opening it.",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}")
        return 0
    if not port_available(args.port):
        raise SystemExit(
            f"{PRODUCT}: port {args.port} is used by another application.\n"
            f"Choose a free port, for example: start-abaqus-qol.cmd --port {args.port + 1}"
        )
    lock = acquire_lock()
    if lock is not True:
        # A simultaneous launch won the race; join it instead of starting another worker.
        port = lock.get("port", args.port) if isinstance(lock, dict) else args.port
        for _ in range(240):
            if health(port, timeout=0.5):
                print(f"{PRODUCT} started by another launch: http://127.0.0.1:{port}", flush=True)
                if not args.no_browser:
                    webbrowser.open(f"http://127.0.0.1:{port}")
                return 0
            time.sleep(0.25)
        raise SystemExit(f"{PRODUCT}: another launch did not become ready in time.")
    try:
        serve(args.port, browser=not args.no_browser)
    finally:
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
