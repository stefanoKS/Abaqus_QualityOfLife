"""Installed-tool boundaries. Drawings always use private, per-upload directories."""

import os
from pathlib import Path
import subprocess
from typing import Protocol


class StepImporter(Protocol):
    def read_assembly(self, path: Path):
        """Future adapter must return geometry and persistent CAD identity mappings."""
        ...


def oda():
    """Installed ODA converter path. ``ABAQUS_QOL_ODA`` is an alias for ``SEAL_ODA``."""
    raw = os.environ.get("SEAL_ODA", "") or os.environ.get("ABAQUS_QOL_ODA", "")
    path = Path(raw)
    if not raw or not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".exe":
        raise ValueError("DWG converter not configured")
    return path


def convert(path):
    out = path.parent / "converted"
    out.mkdir()
    try:
        result = subprocess.run(
            [str(oda()), str(path.parent), str(out), "ACAD2018", "DXF", "0", "1", "drawing.dwg"],
            cwd=path.parent,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("DWG conversion timed out. Export a clean planar DXF.") from exc
    converted = out / "drawing.dxf"
    if result.returncode or not converted.is_file():
        raise ValueError("ODA conversion failed. Check the installed converter or export DXF.")
    return converted
