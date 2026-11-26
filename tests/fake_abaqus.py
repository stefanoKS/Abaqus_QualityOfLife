"""License-free process double at the Abaqus launcher boundary.

The production API only accepts ABAQUS submissions, so CI exercises the real
HTTP contract, SQLite queue, worker and artifact handling against a launcher
that stands in for ``abq2024``. No solver, license or ODB extraction runs; the
manufactured result is labelled as test evidence in its own notice.

Scenario control is per job directory, so it works for both the in-process
worker and a separately started worker process:

* ``fail-solver``        -> the solver invocation exits non-zero
* ``fail-extract-once``  -> the first extraction exits non-zero, then is removed
"""

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = '''\
import json
import os
import pathlib
import sys
import time

job = pathlib.Path.cwd()
arguments = sys.argv[1:]

if arguments and arguments[0].lower() == "python":
    time.sleep(float(os.environ.get("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "0")))
    if (job / "fail-extract-once").exists():
        (job / "fail-extract-once").unlink()
        print("Manufactured extraction failure")
        raise SystemExit(1)
    plans = [
        name
        for name in (
            "partial-body-only",
            "partial-closing",
            "partial-initial-only",
            "partial-history-only",
            "partial-unreadable-last",
        )
        if (job / name).exists()
    ]
    if plans:
        sys.path.insert(0, __ROOT__)
        sys.path.insert(0, __TESTS__)
        from manufactured_results import write

        write(job, plans[0])
        raise SystemExit(0)
    sys.path.insert(0, __ROOT__)
    from packages.engineering.model import Project
    from integrations.abaqus.results import write_playback

    setup = Project.model_validate(json.loads((job / "setup.json").read_text(encoding="utf-8")))
    mesh = json.loads((job / "mesh.json").read_text(encoding="utf-8"))
    metadata = json.loads((job / "result-metadata.json").read_text(encoding="utf-8"))
    write_playback(
        setup,
        mesh,
        job,
        (metadata.get("fixture") or {}).get("nodes"),
        mode="ABAQUS",
        notice="MANUFACTURED TEST EVIDENCE - not an Abaqus analysis.",
    )
    raise SystemExit(0)

print("Manufactured solve started", flush=True)
if (job / "fail-solver-with-odb").exists():
    (job / "analysis.sta").write_text("THE ANALYSIS HAS NOT BEEN COMPLETED\\n", encoding="ascii")
    (job / "analysis.odb").write_bytes(b"manufactured partial ODB candidate\\n")
    if not any((job / name).exists() for name in (
        "partial-body-only", "partial-closing", "partial-initial-only",
        "partial-history-only", "partial-unreadable-last",
    )):
        (job / "partial-closing").touch()
    print("Manufactured solver failure with a saved ODB")
    raise SystemExit(1)

if (job / "fail-solver").exists():
    (job / "analysis.sta").write_text("THE ANALYSIS HAS NOT BEEN COMPLETED\\n", encoding="ascii")
    print("Manufactured solver failure")
    raise SystemExit(1)

# A slow solve that has already written a readable ODB candidate when the
# engineer cancels it (Gate 4 recovery path).
if (job / "odb-before-slow").exists():
    (job / "analysis.sta").write_text("1 1 1 0 1 0 0.1 0.1 0.1\\n", encoding="ascii")
    (job / "analysis.odb").write_bytes(b"manufactured readable ODB\\n")

time.sleep(float(os.environ.get("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "0.2")))
(job / "analysis.sta").write_text(
    "1 1 1 0 1 0 0.1 0.1 0.1\\nTHE ANALYSIS HAS COMPLETED SUCCESSFULLY\\n", encoding="ascii"
)
(job / "analysis.odb").write_bytes(b"manufactured test ODB\\n")
raise SystemExit(0)
'''


def install(tmp_path):
    """Write the double and return the launcher path for ``SIMPLIFY_ABAQUS_LAUNCHER``."""
    import os
    import sys

    directory = Path(tmp_path) / "fake-abaqus"
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "fake_abaqus.py"
    script.write_text(
        SCRIPT.replace("__ROOT__", repr(str(ROOT))).replace(
            "__TESTS__", repr(str(Path(__file__).resolve().parent))
        ),
        encoding="utf-8",
    )
    python = Path(sys.executable)
    if os.name == "nt":
        launcher = directory / "abq2024.cmd"
        launcher.write_text(
            "@echo off\r\n"
            f'"{python}" "{script}" %*\r\n'
            "exit /b %ERRORLEVEL%\r\n",
            encoding="ascii",
        )
    else:
        launcher = directory / "abq2024"
        launcher.write_text(
            '#!/bin/sh\n"{}" "{}" "$@"\n'.format(python, script), encoding="utf-8"
        )
        launcher.chmod(0o755)
    return launcher
