"""Package a production extraction directory as a portable ``.aqresult``.

Used only for local acceptance of an external reference ODB: the result was
produced by the production extractor, then packaged through the same container
code the worker uses. The setup member is an explicit empty reference document;
the result instances and frames are the measured extraction.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.engineering import portable  # noqa: E402
from packages.engineering.geometry import empty  # noqa: E402


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", default="External door-panel reference")
    args = parser.parse_args()
    directory = args.directory
    index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    setup = empty(args.name).model_dump(mode="json")
    frames = {}
    for entry in index.get("frames") or []:
        name = entry["file"]
        frames[name] = (directory / name).read_bytes()
    history = directory / "history.csv"
    provenance = {
        "job": {
            "id": "external-reference",
            "name": args.name,
            "mode": "ABAQUS",
            "created": None,
            "ended": None,
            "solver": "Succeeded",
            "extraction": "Succeeded",
            "input_hash": None,
        },
        "revision": {"id": "external-reference", "number": 1, "source_id": None},
        "artifacts": {
            "results": digest(directory / "results.json"),
            "history": digest(history) if history.is_file() else None,
            "frames": {name: sha256(payload).hexdigest() for name, payload in frames.items()},
        },
    }
    members = portable.result_container(
        setup,
        index,
        history.read_bytes() if history.is_file() else b"",
        frames,
        provenance,
    )
    written = portable.write_container(
        args.output, portable.RESULT_KIND, members, {"name": args.name}
    )
    print(json.dumps(written, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
