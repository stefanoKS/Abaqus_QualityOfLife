"""Native DWG reading through the application-owned helper.

The helper (``dwg-inventory.exe``) links ACadSharp 3.8.35 (MIT) and decodes the
DWG bytes directly. No ODA converter, no DXF intermediate, no network access and
no CAD application automation take part. The Python boundary only runs the
helper and validates its JSON, so a decode problem surfaces as an actionable
message instead of a partially imported model.
"""

import json
import os
from pathlib import Path
import subprocess

HELPER = Path(__file__).resolve().parent / "bin" / "dwg-inventory.exe"
TIMEOUT = 120
MAX_ENTITIES = 200000
SUPPORTED_VERSIONS = {"AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}

MESSAGES = {
    "usage": "The DWG reader was called without a drawing path.",
    "corrupt": "The file is not a readable DWG drawing.",
    "unsupported-version": "This DWG version is not supported by the installed reader.",
    "decode": "The DWG reader could not decode this drawing.",
}


class DwgError(ValueError):
    """Actionable failure the workspace can show without leaking internals."""


def helper():
    path = HELPER
    if not path.is_file():
        raise DwgError(
            "The native DWG reader is missing from integrations/dwg/bin. "
            "Restore it from the repository; no CAD converter is required."
        )
    return path


def read(path):
    """Return the decoded inventory of ``path`` or raise :class:`DwgError`."""
    path = Path(path)
    if not path.is_file():
        raise DwgError("The uploaded drawing is no longer available.")
    if path.stat().st_size > 8 * 1024 * 1024:
        raise DwgError("Maximum drawing size is 8 MiB.")
    environment = dict(os.environ)
    # The native reader must never fall back to a configured ODA converter.
    for name in ("SEAL_ODA", "ABAQUS_QOL_ODA"):
        environment.pop(name, None)
    try:
        completed = subprocess.run(
            [str(helper()), str(path)],
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise DwgError(
            f"Reading the DWG took longer than {TIMEOUT} s. Simplify the drawing or export a DXF."
        ) from exc
    except OSError as exc:
        raise DwgError(f"The native DWG reader could not start: {exc}") from exc
    text = completed.stdout.decode("utf-8", "replace").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        detail = completed.stderr.decode("utf-8", "replace").strip()[:400]
        raise DwgError(f"The DWG reader returned no usable result. {detail}") from exc
    if "error" in payload:
        code = payload["error"].get("code", "decode")
        message = payload["error"].get("message", "")
        raise DwgError(MESSAGES.get(code, MESSAGES["decode"]) + (f" ({message})" if message else ""))
    if completed.returncode:
        raise DwgError(MESSAGES["decode"] + f" (exit code {completed.returncode})")
    version = payload.get("source", {}).get("version", "")
    if version and version not in SUPPORTED_VERSIONS:
        raise DwgError(f"The drawing header {version} is not a supported DWG version.")
    entities = payload.get("entities", [])
    if not entities:
        raise DwgError("The drawing has no model-space entities to import.")
    if len(entities) > MAX_ENTITIES:
        raise DwgError(f"The drawing has {len(entities)} entities, above the {MAX_ENTITIES} limit.")
    return payload
