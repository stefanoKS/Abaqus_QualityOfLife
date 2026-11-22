"""Global, versioned material library.

Definitions live here as immutable versions. A model revision stores its own
material snapshot (plus an optional ``library_id``/``library_version`` pin), so
editing a library material never rewrites a saved revision and a historical run
never changes. Importing legacy model cards always creates an explicit library
entry; names are never used to merge distinct cards.
"""

from __future__ import annotations

import json
import time

from packages.engineering.model import Material, Project
from services import store

CARD_FIELDS = ("model", "color", "density", "young", "poisson", "c10", "d1", "test_data")


def _card_payload(card: dict) -> dict:
    return {field: card.get(field) for field in CARD_FIELDS}


def _same_card(left: dict, right: dict) -> bool:
    return _card_payload(left) == _card_payload(right)


def _version_row(row) -> dict:
    return {
        "version": int(row["version"]),
        "card": {
            "model": row["model"],
            "color": row["color"],
            "density": row["density"],
            "young": row["young"],
            "poisson": row["poisson"],
            "c10": row["c10"],
            "d1": row["d1"],
            "test_data": json.loads(row["test_data"]),
        },
        "created": row["created"],
        "note": row["note"],
    }


def _latest(db, library_id):
    return db.execute(
        "SELECT * FROM material_versions WHERE library_id=? ORDER BY version DESC LIMIT 1",
        (str(library_id),),
    ).fetchone()


def _summary(db, row, usage_count=0):
    latest = _latest(db, row["id"])
    count = db.execute(
        "SELECT COUNT(*) FROM material_versions WHERE library_id=?", (row["id"],)
    ).fetchone()[0]
    return {
        "id": row["id"],
        "name": row["name"],
        "archived": bool(row["archived"]),
        "created": row["created"],
        "updated": row["updated"],
        "current_version": row["current_version"],
        "version_count": count,
        "usage_count": usage_count,
        "card": _version_row(latest)["card"] if latest else None,
    }


def usage(library_id):
    """Every saved revision that pins this library material."""
    found = []
    with store.connection() as db:
        rows = db.execute(
            "SELECT r.id, r.number, r.project, r.setup, "
            "json_extract(r.setup,'$.name') AS model_name FROM revisions r"
        ).fetchall()
    for row in rows:
        try:
            setup = json.loads(row["setup"])
        except ValueError:
            continue
        for card in setup.get("materials", []):
            if card.get("library_id") != str(library_id):
                continue
            found.append(
                {
                    "revision": row["id"],
                    "project": row["project"],
                    "number": row["number"],
                    "model_name": row["model_name"],
                    "material_id": card.get("id"),
                    "pinned_version": card.get("library_version"),
                }
            )
    return found


def list_materials(query="", include_archived=False):
    with store.connection() as db:
        rows = db.execute(
            "SELECT * FROM material_library ORDER BY name COLLATE NOCASE, created"
        ).fetchall()
        result = []
        for row in rows:
            if row["archived"] and not include_archived:
                continue
            if query and query.casefold() not in row["name"].casefold():
                continue
            result.append(_summary(db, row, len(usage(row["id"]))))
    return result


def get(library_id):
    with store.connection() as db:
        row = db.execute(
            "SELECT * FROM material_library WHERE id=?", (str(library_id),)
        ).fetchone()
        if row is None:
            raise KeyError("Material not found")
        versions = [
            _version_row(item)
            for item in db.execute(
                "SELECT * FROM material_versions WHERE library_id=? ORDER BY version",
                (str(library_id),),
            ).fetchall()
        ]
        summary = _summary(db, row, len(usage(row["id"])))
    return {**summary, "versions": versions, "usage": usage(library_id)}


def _insert_version(db, library_id, card, note):
    version = (
        db.execute(
            "SELECT COALESCE(MAX(version),0)+1 FROM material_versions WHERE library_id=?",
            (str(library_id),),
        ).fetchone()[0]
    )
    db.execute(
        "INSERT INTO material_versions(library_id, version, model, color, density, young, "
        "poisson, c10, d1, test_data, created, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(library_id),
            version,
            card["model"],
            card["color"],
            float(card["density"]),
            None if card.get("young") is None else float(card["young"]),
            None if card.get("poisson") is None else float(card["poisson"]),
            None if card.get("c10") is None else float(card["c10"]),
            None if card.get("d1") is None else float(card["d1"]),
            json.dumps(card.get("test_data") or [], separators=(",", ":")),
            time.time(),
            note,
        ),
    )
    db.execute(
        "UPDATE material_library SET current_version=?, updated=? WHERE id=?",
        (version, time.time(), str(library_id)),
    )
    return version


def create(name, card, note=""):
    library_id = store.new_id()
    now = time.time()
    with store.connection(True) as db:
        db.execute(
            "INSERT INTO material_library VALUES (?,?,?,?,?,?)",
            (library_id, name, 0, now, now, 1),
        )
        _insert_version(db, library_id, card, note)
    return get(library_id)


def update(library_id, name=None, card=None, note=""):
    with store.connection(True) as db:
        row = db.execute(
            "SELECT * FROM material_library WHERE id=?", (str(library_id),)
        ).fetchone()
        if row is None:
            raise KeyError("Material not found")
        if row["archived"]:
            raise store.Conflict("Restore this material before editing it.")
        latest = _latest(db, library_id)
        if name is not None:
            db.execute(
                "UPDATE material_library SET name=?, updated=? WHERE id=?",
                (name, time.time(), str(library_id)),
            )
        if card is not None and not _same_card(_version_row(latest)["card"], card):
            _insert_version(db, library_id, card, note)
    return get(library_id)


def duplicate(library_id, name=None):
    source = get(library_id)
    return create(name or source["name"][:150] + " · copy", source["card"], "Duplicated")


def set_archived(library_id, archived):
    with store.connection(True) as db:
        row = db.execute(
            "SELECT * FROM material_library WHERE id=?", (str(library_id),)
        ).fetchone()
        if row is None:
            raise KeyError("Material not found")
        db.execute(
            "UPDATE material_library SET archived=?, updated=? WHERE id=?",
            (1 if archived else 0, time.time(), str(library_id)),
        )
    return get(library_id)


def import_from_revision(revision_id, material_ids=()):
    """Create an explicit library entry for selected model-local cards.

    Existing pins are returned unchanged. Cards are never merged by name; each
    newly imported card becomes a separate library material.
    """
    revision = store.revision(revision_id)
    setup = Project.model_validate(revision["setup"])
    wanted = set(material_ids)
    result = []
    for card in setup.materials:
        if wanted and card.id not in wanted:
            continue
        if card.library_id:
            result.append(
                {
                    "material_id": card.id,
                    "library_id": card.library_id,
                    "version": card.library_version or 1,
                    "existing": True,
                }
            )
            continue
        payload = {
            "model": card.model,
            "color": card.color,
            "density": card.density,
            "young": card.young,
            "poisson": card.poisson,
            "c10": card.c10,
            "d1": card.d1,
            "test_data": [list(row) for row in card.test_data],
        }
        created = create(
            card.name,
            payload,
            f"Imported from revision {revision_id} ({revision['number']})",
        )
        result.append(
            {
                "material_id": card.id,
                "library_id": created["id"],
                "version": created["current_version"],
                "existing": False,
            }
        )
    return result


def definition_for_material(material: Material) -> dict:
    """The library card payload of a model material snapshot."""
    return {
        "model": material.model,
        "color": material.color,
        "density": material.density,
        "young": material.young,
        "poisson": material.poisson,
        "c10": material.c10,
        "d1": material.d1,
        "test_data": [list(row) for row in material.test_data],
    }
