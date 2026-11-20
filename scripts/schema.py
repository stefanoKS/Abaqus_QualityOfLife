"""Regenerate the browser contract from the same models served by FastAPI."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.api.main import app  # noqa: E402 - run directly from the repository.

web = ROOT / "apps/web"
scratch = ROOT / ".local/openapi.json"
scratch.parent.mkdir(exist_ok=True)
schema = app.openapi()
# TypeScript has no regex-constrained index signatures. Pydantic still checks CAD IDs.
for model in schema["components"]["schemas"].values():
    for prop in model.get("properties", {}).values():
        patterns = prop.get("patternProperties", {})
        if len(patterns) == 1 and "additionalProperties" not in prop:
            prop["additionalProperties"] = next(iter(patterns.values()))
scratch.write_text(json.dumps(schema), encoding="utf-8")
subprocess.run(
    [
        "node",
        str(web / "node_modules/openapi-typescript/bin/cli.js"),
        str(scratch),
        "--output",
        str(web / "src/generated.ts"),
        "--default-non-nullable",
        "true",
    ],
    check=True,
)
