"""Run the loopback API and built UI alongside a separate queue worker."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import uvicorn

ROOT = Path(__file__).resolve().parents[1]


def serve(port, test_data=None):
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    if not (ROOT / "apps/web/dist/index.html").is_file():
        raise SystemExit("Build the browser first: npm --prefix apps/web run build")
    if test_data:
        os.environ["SEAL_DATA"] = test_data
        os.environ.pop("ABAQUS_QOL_DATA", None)
        os.environ.pop("SIMPLIFY_ABAQUS_LAUNCHER", None)
        os.environ.pop("ABAQUS_QOL_LAUNCHER", None)
        os.environ.pop("SEAL_ODA", None)
        os.environ.pop("ABAQUS_QOL_ODA", None)
    from services import store
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    stop = store.root() / ("stop-" + uuid4().hex)
    args = [sys.executable, "-m", "services.worker", "--stop-file", str(stop)]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    worker = subprocess.Popen(args, cwd=ROOT, creationflags=flags)
    try:
        print(f"Abaqus QOL http://127.0.0.1:{port} · worker PID {worker.pid}", flush=True)
        uvicorn.run("services.api.main:app", host="127.0.0.1", port=port, log_level="warning")
    finally:
        stop.touch()
        print("Waiting for the worker to finish its current operation…", flush=True)
        worker.wait()
        stop.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--test-data", action="store_true", help="Temporary isolated database for browser tests"
    )
    args = parser.parse_args()
    if args.test_data:
        with tempfile.TemporaryDirectory(prefix="seal-browser-") as directory:
            serve(args.port, directory)
    else:
        serve(args.port)
