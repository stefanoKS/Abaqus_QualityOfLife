"""Host-side, explicitly configured commands. All job arguments are built internally."""

import os
from pathlib import Path
import re
import shutil
import signal
import subprocess

ENV_LAUNCHER = "SIMPLIFY_ABAQUS_LAUNCHER"
ENV_LAUNCHER_ALIAS = "ABAQUS_QOL_LAUNCHER"
HERE = Path(__file__).resolve().parent


def launcher_setting():
    """Return the configured launcher variable name and value.

    The legacy variable wins so existing startup scripts keep working exactly as
    before; the new alias is only consulted when the legacy one is unset.
    """
    for name in (ENV_LAUNCHER, ENV_LAUNCHER_ALIAS):
        value = os.environ.get(name)
        if value:
            return name, value
    return ENV_LAUNCHER, ""


def _launcher(value, name=ENV_LAUNCHER):
    if not value:
        raise ValueError(
            f"Abaqus launcher not configured. Set {ENV_LAUNCHER} "
            f"(or its alias {ENV_LAUNCHER_ALIAS}) to the installed launcher."
        )
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Abaqus launcher must be an existing absolute file path.")
    path = path.resolve()
    if os.name == "nt":
        if path.suffix.lower() not in (".bat", ".cmd", ".exe"):
            raise ValueError("Select an Abaqus .bat, .cmd or .exe launcher.")
        # Batch commands receive an extra cmd.exe parse. Reject expansion/control syntax.
        if str(path).startswith("\\\\") or re.search(r'[%!&|<>^"\r\n]', str(path)):
            raise ValueError("Use a local launcher path without shell metacharacters.")
    elif not os.access(path, os.X_OK):
        raise ValueError("Configured Abaqus launcher is not executable.")
    return path


def configured_launcher():
    _, value = launcher_setting()
    return _launcher(value)


def _start(path, arguments, job_dir, log_stream):
    path = _launcher(path)
    kwargs = {
        "cwd": job_dir,
        "stdout": log_stream,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        if path.suffix.lower() in (".bat", ".cmd"):
            # Fixed ASCII arguments only. Use cmd's documented /s outer-quote rule.
            system_cmd = Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"
            kwargs["executable"] = str(system_cmd)
            command = f'"{system_cmd}" /d /v:off /s /c ""{path}" {" ".join(arguments)}"'
            return subprocess.Popen(command, **kwargs)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen([str(path), *arguments], **kwargs)


def start_solver(launcher, job_dir, cpus, log_stream):
    if type(cpus) is not int or not 1 <= cpus <= 32:
        raise ValueError("Choose an integer CPU count from 1 to 32.")
    if not (Path(job_dir) / "analysis.inp").is_file():
        raise ValueError("Submitted analysis.inp is missing.")
    if any(
        (Path(job_dir) / name).exists() for name in ("analysis.odb", "analysis.sta", "analysis.lck")
    ):
        raise ValueError("Existing Abaqus job artifacts detected. Use a fresh run directory.")
    return _start(
        launcher,
        ["job=analysis", "input=analysis.inp", f"cpus={cpus}", "interactive"],
        job_dir,
        log_stream,
    )


def start_extraction(launcher, job_dir, log_stream):
    job_dir = Path(job_dir)
    if not (job_dir / "analysis.odb").is_file() or not (job_dir / "result-metadata.json").is_file():
        raise ValueError("Extraction requires analysis.odb and its submitted metadata.")
    # A cancelled previous extraction may have finished writing just before cancellation.
    # Its index cannot count as success evidence for the new invocation.
    (job_dir / "results.json").unlink(missing_ok=True)
    # Importable pure stdlib helpers live next to the extractor under safe internal names.
    for filename in ("extract_odb.py", "interchange.py"):
        shutil.copyfile(HERE / filename, job_dir / filename)
    return _start(launcher, ["python", "extract_odb.py"], job_dir, log_stream)


def stop_process(process):
    """Terminate descendants of this worker's live Popen handle. Never rediscover by image name."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        killer = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
        result = subprocess.run(
            [str(killer), "/pid", str(process.pid), "/t", "/f"],
            capture_output=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode and process.poll() is None:
            raise RuntimeError("Cancellation could not confirm termination of this process tree.")
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def tail(path, limit=65536):
    try:
        with Path(path).open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - limit))
            return stream.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def progress(job_dir):
    directory = Path(job_dir)
    sta = tail(directory / "analysis.sta")
    for line in reversed(sta.splitlines()):
        columns = line.split()
        # Standard implicit status rows: STEP INC ATT SEVERE EQUIL TOTAL TOTAL-TIME STEP-TIME DT.
        if len(columns) < 9 or not all(x.isdigit() for x in columns[:3]):
            continue
        try:
            return {
                "phase": "Running",
                "step": int(columns[0]),
                "increment": int(columns[1]),
                "step_time": float(columns[7].replace("D", "E")),
            }
        except ValueError:
            continue
    messages = tail(directory / "analysis.log") + tail(directory / "solver.log")
    if re.search(
        r"(?:waiting for|queued for).*licen[cs]e|licen[cs]e.*(?:queued|waiting)", messages, re.I
    ):
        return {"phase": "Waiting for license"}
    return {"phase": "Running"}


def solver_evidence(job_dir, exit_code):
    directory = Path(job_dir)
    status = tail(directory / "analysis.sta")
    diagnostic = "\n".join(
        tail(directory / f) for f in ("analysis.msg", "analysis.dat", "analysis.log", "solver.log")
    )
    license_error = re.search(
        r"(?:licen[cs]e.*(?:denied|failed|error|unavailable)|"
        r"(?:unable|failed|cannot|could not).*?(?:checkout|check out|licen[cs]e))",
        diagnostic,
        re.I,
    )
    if license_error:
        return (
            False,
            "Abaqus license checkout failed. Check the configured license service and solver entitlements.",
        )
    if exit_code != 0:
        return False, f"Abaqus launcher exited with code {exit_code}. Inspect solver diagnostics."
    if re.search(
        r"\*{3}(?:ERROR|FATAL)|THE ANALYSIS HAS NOT BEEN COMPLETED", diagnostic + status, re.I
    ):
        return (
            False,
            "Abaqus reported an analysis error. Inspect the status, message and data files.",
        )
    if not re.search(r"THE ANALYSIS HAS COMPLETED SUCCESSFULLY", status, re.I):
        return False, "Missing Abaqus/Standard completion evidence in analysis.sta."
    odb_path = directory / "analysis.odb"
    if not odb_path.is_file() or not odb_path.stat().st_size:
        return False, "Analysis completion reported but analysis.odb is missing or empty."
    return True, "Abaqus/Standard reported successful completion and produced an ODB."
