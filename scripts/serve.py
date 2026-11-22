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

# `python scripts/serve.py` puts `scripts/`, not the repository root, on sys.path.
# The launcher must be able to import `services` even when it is invoked from
# another working directory, otherwise the instance-identity check silently
# degrades to "unidentifiable" and a second double-click refuses to reuse.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def lock_path(port):
    """One lock per port, so a custom-port launch never joins the default instance."""
    return ROOT / ".local" / f"serve-{port}.lock"

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


def local_identity():
    """Build identity of the code in this checkout, read without starting services."""
    try:
        from services import store
        from services.api.main import API_VERSION, BUILD, FRONTEND

        return {
            "build": BUILD,
            "frontend": FRONTEND,
            "api": API_VERSION,
            "data": store.data_identity(),
        }
    except Exception:  # a broken checkout reports itself as unidentifiable
        return {"build": "", "frontend": "", "api": 0, "data": ""}


def compatibility(payload):
    """Classify an instance found on the port: ``current`` or a reason it is not."""
    if not payload:
        return "not-ours"
    if not payload.get("build") or not payload.get("api"):
        return "legacy"
    expected = local_identity()
    if payload.get("data") and expected.get("data") and payload["data"] != expected["data"]:
        return "different-data"
    if payload.get("api") != expected.get("api"):
        return "different-api"
    if payload.get("build") != expected["build"]:
        return "different-build"
    return "current"


def describe(payload):
    return (
        f"PID {payload.get('pid')}, started {time.strftime('%Y-%m-%d %H:%M', time.localtime(payload.get('started', 0)))}, "
        f"version {payload.get('version', 'unknown')}, build {payload.get('build') or 'unidentified (older release)'}"
        + (f", git {payload['git']}" if payload.get("git") else "")
        + (f", frontend {payload['frontend']}" if payload.get("frontend") else "")
    )


def suspicious_process(job):
    """True when a terminal-looking job still has a matching live process.

    A recorded solver PID is only trusted together with its process start time,
    so PID reuse cannot make an idle instance look busy — or a busy one idle.
    """
    pid = job.get("pid")
    if not pid:
        return False
    try:
        import psutil

        process = psutil.Process(int(pid))
        created = process.create_time()
        command = " ".join(process.cmdline()).lower()
    except Exception:
        return False
    recorded = job.get("process_started") or job.get("started")
    if recorded and abs(created - float(recorded)) > 5:
        return False
    return "abaqus" in command or "services.worker" in command


def active_jobs(port, timeout=2.0):
    """Unsafe jobs on the running instance; ``None`` when coverage is unknown.

    Only ``/api/jobs`` is authoritative: it reports every durable mode and an
    ``activity`` classification. An older API that cannot prove that coverage is
    treated as unreadable (fail closed), never as idle. ``terminal`` count is
    rechecked against live processes so an unresolved solver still blocks.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/jobs", timeout=timeout
        ) as response:
            coverage = response.headers.get("X-Abaqus-QOL-Jobs", "")
            jobs = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    if coverage != "all-modes-v1":
        # An older endpoint may omit IMPORT/MESH/DECK entirely. An empty list
        # from it is not evidence of inactivity.
        return None
    if not isinstance(jobs, list):
        return None
    if any(
        not isinstance(job, dict) or "activity" not in job or "mode" not in job
        for job in jobs
    ):
        return None
    unsafe = []
    for job in jobs:
        if job.get("activity") != "terminal" or suspicious_process(job):
            unsafe.append(job)
    return unsafe


def stop_instance(port):
    """Stop only processes positively identified as this product's API/worker.

    Never an Abaqus solver, never a process matched only by executable name. If
    process inspection is unavailable, nothing is stopped (the caller then fails
    because the port is still busy).
    """
    payload = health(port) or {}
    try:
        import psutil
    except ImportError:
        return []
    pids = {payload.get("pid")}
    data = str(store_root())
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            command = " ".join(process.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        # A worker is ours only when it runs the worker module on this data directory.
        if "services.worker" in command and data in command:
            pids.add(process.info["pid"])
    stopped = []
    for pid in pids:
        if not pid:
            continue
        try:
            process = psutil.Process(pid)
            created = process.create_time()
            command = " ".join(process.cmdline())
        except Exception:
            continue
        lower = command.lower()
        if "abaqus" in lower:
            continue
        if "services.api" not in command and "uvicorn" not in lower and "services.worker" not in command:
            continue
        if int(pid) == int(payload.get("pid") or 0) and payload.get("started"):
            # PID reuse must not let us stop an unrelated process.
            if abs(created - float(payload["started"])) > 5:
                continue
        if "services.worker" in command and data not in command:
            continue
        process.terminate()
        stopped.append(pid)
    for pid in stopped:
        try:
            psutil.Process(pid).wait(timeout=10)
        except Exception:
            pass
    for _ in range(40):
        if port_available(port):
            return stopped
        time.sleep(0.25)
    return stopped


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


def pid_alive(pid):
    try:
        import psutil

        return bool(pid) and psutil.pid_exists(int(pid))
    except (ImportError, TypeError, ValueError):
        try:
            os.kill(int(pid), 0)
        except (OSError, TypeError, ValueError):
            return False
        return True


def acquire_lock(port):
    """Return ``True`` when this launch owns the port lock, or the owner's details.

    A simultaneous cold launch must not steal the lock from the launch that is
    still booting: the owner is only replaced when its process is gone or the
    record is old enough to be certainly abandoned.
    """
    path = lock_path(port)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"pid": os.getpid(), "port": port, "started": time.time()}
                    )
                )
            return True
        except FileExistsError:
            try:
                owner = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                owner = {}
            if health(owner.get("port", port), timeout=0.5):
                return owner
            age = time.time() - float(owner.get("started") or 0)
            if pid_alive(owner.get("pid")) and age < 180:
                # Another launch is still starting. Join it rather than replacing
                # its lock and starting a second worker.
                return owner
            # A crashed launch left the lock behind; take it over.
            path.unlink(missing_ok=True)
    return None


def store_root():
    from services import store

    return store.root()


def serve(port, test_data=None, browser=True):
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    os.environ["ABAQUS_QOL_PORT"] = str(port)
    if not (WEB / "dist/index.html").is_file():
        raise SystemExit(f"{PRODUCT}: build the browser first: npm --prefix apps/web run build")
    from services import release as release_mod

    override = os.environ.get("ABAQUS_QOL_WEB_DIST", "").strip()
    resolved = release_mod.resolve(WEB, Path(override) if override else None)
    if not resolved.valid:
        raise SystemExit(
            f"{PRODUCT}: browser release {resolved.id} is incomplete "
            f"({resolved.broken}). Rebuild it with: npm --prefix apps/web run build"
        )
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
        # Automated tests exercise the real API, queue, worker and artifacts
        # against a launcher double. No solver, license or ODA conversion runs.
        sys.path.insert(0, str(ROOT / "tests"))
        from fake_abaqus import install as install_double

        os.environ["SIMPLIFY_ABAQUS_LAUNCHER"] = str(install_double(store_root()))
        os.environ.setdefault("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "3")
    # Refuse a second API/worker pair on the same data directory before the
    # worker can claim anything. The record is released by the API lifespan.
    from services import ownership, store

    try:
        store.claim_data_root(os.getpid(), port)
    except store.Conflict as error:
        raise SystemExit(f"{PRODUCT}: {error}") from None
    # An API may attach to an existing worker, but a launcher never starts a
    # second worker beside one. This is the fail-closed check for the orphaned
    # worker a supervisor crash can leave behind.
    if not ownership.worker_lock_free(store_root()):
        store.release_data_root(os.getpid())
        record = store.read_instance() or {}
        raise SystemExit(
            f"{PRODUCT}: a worker (PID {record.get('worker_pid') or 'unknown'}) is still "
            f"running on data directory {store_root()}. Wait for it to finish or close it "
            "manually, then start again. Nothing was stopped."
        )
    import uvicorn

    stop = store_root() / ("stop-" + uuid4().hex)
    args = [sys.executable, "-m", "services.worker", "--stop-file", str(stop)]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    worker = subprocess.Popen(args, cwd=ROOT, creationflags=flags)
    # The worker claims its own OS lock. If it exits immediately (an orphaned
    # worker or another owner won a race), do not leave an API without a worker.
    time.sleep(0.4)
    if worker.poll() is not None:
        store.release_data_root(os.getpid())
        raise SystemExit(
            f"{PRODUCT}: the worker could not take ownership of {store_root()} "
            f"(exit code {worker.returncode}). Nothing was started."
        )
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
        # Ownership is released only after the worker has exited, so a fresh
        # launch cannot take the directory while a solver child may still run.
        store.release_data_root(os.getpid())


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"{PRODUCT} local workbench launcher")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--test-data", action="store_true", help="Temporary isolated database for browser tests"
    )
    parser.add_argument("--status", action="store_true", help="report the instance on the port and exit")
    parser.add_argument("--takeover", action="store_true", help="stop a stale instance when no job is active")
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
    if args.status:
        if existing:
            print(f"{PRODUCT} on port {args.port}: {describe(existing)}")
            print(f"  compatibility: {compatibility(existing)}")
        else:
            print(f"{PRODUCT}: nothing is serving port {args.port}.")
        return 0
    if existing and compatibility(existing) == "current":
        print(
            f"{PRODUCT} is already running on http://127.0.0.1:{args.port} ({describe(existing)}). "
            "Opening the running instance.",
            flush=True,
        )
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}")
        return 0
    if existing:
        verdict = compatibility(existing)
        reason = {
            "legacy": "it predates the build identity fields, so it is an older release",
            "different-build": "it runs a different browser/API release than this checkout",
            "different-api": "it runs a different API generation than this browser build",
            "different-data": "it owns a different data directory than this launch",
        }.get(verdict, "it could not be identified")
        running = active_jobs(args.port)
        print(
            f"{PRODUCT}: port {args.port} is served by a different instance ? {reason}.\n"
            f"  running : {describe(existing)}\n"
            f"  expected: build {local_identity()['build'] or 'this checkout'}",
            flush=True,
        )
        if running is None:
            print("  jobs    : could not be read from the running instance", flush=True)
            raise SystemExit(
                f"{PRODUCT}: refusing to take over port {args.port} because the running "
                "instance's job state could not be established. Confirm its activity, close "
                "it manually, then start again. Nothing was stopped."
            )
        elif running:
            names = ", ".join(f"{job.get('name')} ({job.get('status')})" for job in running[:5])
            print(f"  jobs    : {len(running)} still active ? {names}", flush=True)
        else:
            print("  jobs    : none queued or running", flush=True)
        if not args.takeover:
            print(
                "Nothing was stopped. To switch to this checkout safely, close that instance and\n"
                "run the startup file again, or repeat the command with --takeover, which stops only\n"
                "the Abaqus QOL API and worker for this data directory after checking for active jobs.",
                flush=True,
            )
            return 3
        if running:
            raise SystemExit(
                f"{PRODUCT}: refusing to stop the running instance while {len(running)} job(s) are "
                "active. Wait for them to finish, then run again with --takeover."
            )
        # Recheck immediately before stopping anything: a job may have been
        # queued between the first read and this point.
        recheck = active_jobs(args.port)
        if recheck is None:
            raise SystemExit(
                f"{PRODUCT}: refusing to take over port {args.port}: job activity could not "
                "be re-established immediately before stopping. Nothing was stopped."
            )
        if recheck:
            raise SystemExit(
                f"{PRODUCT}: refusing to stop the running instance: "
                f"{len(recheck)} job(s) became active. Wait for them to finish. Nothing was stopped."
            )
        stopped = stop_instance(args.port)
        print(f"  stopped : {stopped or 'nothing (already gone)'}", flush=True)
        if not port_available(args.port):
            raise SystemExit(
                f"{PRODUCT}: port {args.port} is still busy after stopping the old instance."
            )
    if not port_available(args.port):
        raise SystemExit(
            f"{PRODUCT}: port {args.port} is used by another application.\n"
            f"Choose a free port, for example: start-abaqus-qol.cmd --port {args.port + 1}"
        )
    lock = acquire_lock(args.port)
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
        lock_path(args.port).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
