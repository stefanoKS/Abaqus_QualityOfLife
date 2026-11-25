"""Gate A evidence for door-panel contact output.

Creates one-step and body-then-door models in an isolated data root, prepares
their decks, compares DOOR_PROFILE_NODES and contact requests, and proves that an
output-only edit leaves mesh identity and the historical INP bytes unchanged.
No solver or license is used.
"""

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".local" / "evidence" / "door-panel-pressure"
DATA = EVIDENCE / "gate-a-data"
os.environ["SEAL_DATA"] = str(DATA)
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from services import store  # noqa: E402
from services.api.main import app  # noqa: E402
from services.worker.__main__ import once  # noqa: E402


def worker(owner="gate-a"):
    for _ in range(20):
        if not once(owner):
            return
    raise SystemExit("worker kept claiming jobs")


def post(api, path, data):
    response = api.post(path, json=data)
    assert response.is_success, response.text
    return response.json()


def prepare(api, revision, template):
    project = post(
        api,
        "/api/projects",
        {"name": "Door pressure " + template, "example": True, "template": template},
    )
    mesh = post(api, "/api/meshes", {"revision": project["id"], "token": store.new_id()})
    worker()
    mesh_job = store.job(mesh["id"])
    assert mesh_job["status"] == "Completed", mesh_job["diagnostic"]
    resolved = post(api, "/api/meshes/" + mesh["id"] + "/fixture/edges", {})
    saved = api.put(
        "/api/meshes/" + mesh["id"] + "/fixture", json={"labels": resolved["labels"]}
    )
    assert saved.is_success, saved.text
    deck = post(
        api,
        "/api/decks",
        {
            "revision": project["id"],
            "token": store.new_id(),
            "mesh": mesh["id"],
            "fixture_hash": resolved["hash"],
        },
    )
    worker()
    deck_job = store.job(deck["id"])
    assert deck_job["status"] == "Completed", deck_job["diagnostic"]
    return project, mesh_job, deck_job, resolved


def nset_labels(text, name, instance):
    block = re.search(
        r"\*Nset, nset=" + name + r", instance=" + instance + r"\s*\n(.*?)(?=\n\*)",
        text,
        re.S,
    )
    assert block, f"missing {name} on {instance}"
    return [int(value) for value in re.findall(r"\d+", block.group(1))]


def part_nodes(text, part):
    block = re.search(r"\*Part, name=" + part + r"\s*\n\*Node\s*\n(.*?)(?=\n\*)", text, re.S)
    assert block, f"missing part {part}"
    rows = [line.strip() for line in block.group(1).splitlines() if line.strip()]
    return sorted(int(row.split(",")[0]) for row in rows)


def step_blocks(text):
    pieces = text.split("*Step, name=")
    return pieces[1:]


def deck_facts(text, two_step):
    panel_nodes = part_nodes(text, "PANEL")
    seal_nodes = part_nodes(text, "WS")
    rp = nset_labels(text, "PANEL_RP", "PANEL-1")[0]
    labels = nset_labels(text, "DOOR_PROFILE_NODES", "PANEL-1")
    # The PANEL part node block also carries the rigid reference point; it is a
    # node but never part of the geometric door profile.
    geometric = sorted(node for node in panel_nodes if node != rp)
    blocks = step_blocks(text)
    facts = {
        "panel_nodes": len(geometric),
        "door_set_labels": len(labels),
        "door_set_unique": len(labels) == len(set(labels)),
        "door_set_equals_geometric": sorted(labels) == geometric,
        "reference_point_excluded": rp not in labels,
        "seal_nodes_excluded": not (set(labels) & set(seal_nodes)),
        "steps": len(blocks),
        "door_outputs_per_step": [block.count("*Contact Output, nset=DOOR_PROFILE_NODES") for block in blocks],
        "global_cstress_per_step": [block.count("*Contact Output\nCSTRESS") for block in blocks],
        "door_force_per_step": [block.count("CFORCE") for block in blocks],
        "both_fields_on_door": [
            "CFORCE, CSTRESS" in block for block in blocks
        ],
        "u_requested": all(
            re.search(r"\*Node Output\s*\n[^\n]*\bU\b", block) is not None for block in blocks
        ),
        "reference_point_nset": rp,
        "two_step_expected": two_step,
    }
    # Exactly one formulation per step: either global CSTRESS + door CFORCE, or
    # both fields on the door set.
    facts["request_count_ok"] = all(
        (global_one and door_one and not both)
        or (not global_one and door_one and both)
        for global_one, door_one, both in zip(
            facts["global_cstress_per_step"],
            facts["door_outputs_per_step"],
            facts["both_fields_on_door"],
        )
    )
    return facts


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report = {}
    with TestClient(app, base_url="http://127.0.0.1") as api:
        for template, two_step in (("hollow", False), ("two-panel", True)):
            project, mesh, deck, fixture = prepare(api, None, template)
            text = (store.job_dir(deck["id"]) / "analysis.inp").read_text(encoding="utf-8")
            facts = deck_facts(text, two_step)
            assert facts["door_set_unique"] and facts["door_set_equals_geometric"]
            assert facts["reference_point_excluded"] and facts["seal_nodes_excluded"]
            assert facts["steps"] == (2 if two_step else 1)
            assert all(count == 1 for count in facts["door_outputs_per_step"])
            assert facts["request_count_ok"] and facts["u_requested"]
            first_hash = store.digest(store.job_dir(deck["id"]) / "analysis.inp")
            first_bytes = (store.job_dir(deck["id"]) / "analysis.inp").read_bytes()

            # Output-only edit: same mesh identity, new revision and new deck.
            setup = store.revision(project["id"])["setup"]
            setup["analysis"]["door_pressure"] = False
            response = api.put(
                "/api/projects/" + project["project"],
                json={"base": project["id"], "setup": setup},
            )
            assert response.is_success, response.text
            edited = response.json()
            assert edited["mesh_compat"] == mesh["mesh_compat"]
            off_deck = post(
                api,
                "/api/decks",
                {
                    "revision": edited["id"],
                    "token": store.new_id(),
                    "mesh": mesh["id"],
                    "fixture_hash": fixture["hash"],
                },
            )
            worker()
            off_job = store.job(off_deck["id"])
            assert off_job["status"] == "Completed", off_job["diagnostic"]
            off_text = (store.job_dir(off_job["id"]) / "analysis.inp").read_text(encoding="utf-8")
            off_hash = store.digest(store.job_dir(off_job["id"]) / "analysis.inp")
            assert "DOOR_PROFILE_NODES" not in off_text
            assert off_hash != first_hash
            # The original deck bytes are immutable.
            assert (store.job_dir(deck["id"]) / "analysis.inp").read_bytes() == first_bytes

            # Turn it back on: the deterministic deck returns to the same bytes.
            setup = store.revision(edited["id"])["setup"]
            setup["analysis"]["door_pressure"] = True
            response = api.put(
                "/api/projects/" + project["project"],
                json={"base": edited["id"], "setup": setup},
            )
            assert response.is_success, response.text
            reverted = response.json()
            on_deck = post(
                api,
                "/api/decks",
                {
                    "revision": reverted["id"],
                    "token": store.new_id(),
                    "mesh": mesh["id"],
                    "fixture_hash": fixture["hash"],
                },
            )
            worker()
            on_job = store.job(on_deck["id"])
            assert on_job["status"] == "Completed", on_job["diagnostic"]
            on_hash = store.digest(store.job_dir(on_job["id"]) / "analysis.inp")
            report[template] = {
                "model": project["project"],
                "revision": project["id"],
                "mesh": mesh["id"],
                "mesh_digest": mesh["mesh_digest"],
                "mesh_compat": mesh["mesh_compat"],
                "deck": deck["id"],
                "inp_sha256": first_hash,
                "facts": facts,
                "opt_out": {
                    "revision": edited["id"],
                    "deck": off_job["id"],
                    "inp_sha256": off_hash,
                    "door_set_absent": "DOOR_PROFILE_NODES" not in off_text,
                    "mesh_compat_unchanged": edited["mesh_compat"] == mesh["mesh_compat"],
                    "historical_inp_unchanged": True,
                },
                "opt_in_again": {
                    "revision": reverted["id"],
                    "deck": on_job["id"],
                    "inp_sha256": on_hash,
                    "byte_identical_to_first": on_hash == first_hash,
                },
            }
            print(
                f"{template}: nodes {facts['door_set_labels']} steps {facts['steps']} "
                f"INP {first_hash[:12]} off {off_hash[:12]} on {on_hash[:12]}"
            )
    (EVIDENCE / "gate-a-deck.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("report:", EVIDENCE / "gate-a-deck.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
