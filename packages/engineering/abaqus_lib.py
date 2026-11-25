"""Data-only reader for Abaqus/CAE material library (``.lib``) files.

A ``.lib`` file is a Python protocol-0 pickle written by CAE. It is **never**
executed here: a small bounded interpreter accepts only the data opcodes
(strings, integers, floats, lists, tuples, dicts and memo references) and rejects
every executable opcode (``GLOBAL``/``REDUCE``/``OBJ``/``INST``/``BUILD``). Each
top-level record keeps its original byte span, so an export can write back the
exact bytes CAE produced instead of re-serialising a lookalike.

The nested ``Data`` value is a Python-literal dictionary that also uses CAE
symbolic constants (``OFF``, ``LONG_TERM``, ``ISOTROPIC``...). It is parsed by a
literal tokenizer, not by ``eval``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json

MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 4096


class LibraryError(ValueError):
    """An actionable decode failure; the message never contains a stack trace."""


# --------------------------------------------------------------------- pickle


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.i = 0

    def line(self) -> bytes:
        end = self.data.find(b"\n", self.i)
        if end < 0:
            raise LibraryError("The library file is truncated.")
        raw = self.data[self.i : end]
        self.i = end + 1
        return raw[:-1] if raw.endswith(b"\r") else raw


class _Mark:
    pass


MARK = _Mark()


def _parse(data: bytes):
    """Interpret the protocol-0 stream and return ``(value, spans)``."""
    if len(data) > MAX_BYTES:
        raise LibraryError("The library file exceeds the 8 MiB limit.")
    reader = _Reader(data)
    stack: list = []
    memo: dict[int, object] = {}
    spans: list[tuple[int, int]] = []
    outer = False
    completed = 0

    def pop_items() -> list:
        items = []
        while stack and stack[-1] is not MARK:
            items.append(stack.pop())
        if not stack:
            raise LibraryError("The library file has an unbalanced tuple.")
        stack.pop()
        items.reverse()
        return items

    while True:
        if reader.i >= len(data):
            raise LibraryError("The library file ends before its stop opcode.")
        position = reader.i
        operator = chr(data[reader.i])
        reader.i += 1
        if operator == "(":
            stack.append(MARK)
            if len(stack) == 1:
                outer = True
            elif outer and len(stack) == 2 + completed:
                # A top-level record starts here; nested marks belong to it.
                spans.append((position, -1))
            continue
        if operator == "t":
            stack.append(tuple(pop_items()))
            # The finished record tuple now sits above the outer tuple's MARK.
            if len(stack) == 2 + completed and spans and spans[-1][1] < 0:
                spans[-1] = (spans[-1][0], reader.i)
                completed += 1
        elif operator == "l":
            stack.append(pop_items())
        elif operator == "d":
            items = pop_items()
            stack.append(dict(zip(items[0::2], items[1::2])))
        elif operator == "}":
            stack.append({})
        elif operator == "S":
            raw = reader.line()
            if not (len(raw) >= 2 and raw[:1] in (b"'", b'"') and raw[-1:] == raw[:1]):
                raise LibraryError("The library file contains a malformed string.")
            stack.append(raw[1:-1].decode("latin-1"))
        elif operator == "V":
            stack.append(reader.line().decode("latin-1"))
        elif operator == "I":
            raw = reader.line()
            stack.append(raw == b"01" if raw in (b"01", b"00") else int(raw))
        elif operator == "L":
            stack.append(int(reader.line().rstrip(b"L")))
        elif operator == "F":
            stack.append(float(reader.line()))
        elif operator == "N":
            stack.append(None)
        elif operator == "p":
            memo[int(reader.line())] = stack[-1]
        elif operator == "g":
            key = int(reader.line())
            if key not in memo:
                raise LibraryError("The library file references a missing memo entry.")
            stack.append(memo[key])
        elif operator == "s":
            value = stack.pop()
            key = stack.pop()
            if not isinstance(stack[-1], dict):
                raise LibraryError("The library file has an invalid dictionary update.")
            stack[-1][key] = value
        elif operator == "u":
            items = pop_items()
            if not stack or not isinstance(stack[-1], dict):
                raise LibraryError("The library file has an invalid dictionary batch.")
            for key, value in zip(items[0::2], items[1::2]):
                stack[-1][key] = value
        elif operator == "a":
            value = stack.pop()
            if not isinstance(stack[-1], list):
                raise LibraryError("The library file has an invalid list append.")
            stack[-1].append(value)
        elif operator == "e":
            items = pop_items()
            if not stack or not isinstance(stack[-1], list):
                raise LibraryError("The library file has an invalid list batch.")
            stack[-1].extend(items)
        elif operator == ".":
            break
        else:
            # Every Python opcode that can execute code is rejected here.
            raise LibraryError(
                f"The library file uses an unsupported opcode {operator!r}; "
                "only data opcodes are accepted."
            )
    if not stack:
        raise LibraryError("The library file contains no value.")
    return stack[-1], [span for span in spans if span[1] > span[0]]


# ------------------------------------------------------------- CAE literals


class Symbol(str):
    """A CAE symbolic constant such as ``OFF`` or ``ISOTROPIC``."""


def _literal(text: str):
    tokens = _tokenize(text)
    value, position = _value(tokens, 0)
    if position != len(tokens):
        raise LibraryError("The CAE material data has trailing tokens.")
    return value


def _tokenize(text: str):
    tokens: list[tuple[str, object]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "{}[](),:":
            tokens.append((char, char))
            index += 1
            continue
        if char in "'\"":
            quote = char
            index += 1
            collected = []
            while index < len(text):
                character = text[index]
                if character == "\\" and index + 1 < len(text):
                    collected.append(text[index : index + 2])
                    index += 2
                    continue
                if character == quote:
                    index += 1
                    break
                collected.append(character)
                index += 1
            else:
                raise LibraryError("The CAE material data has an unterminated string.")
            tokens.append(("string", _unescape("".join(collected))))
            continue
        start = index
        while index < len(text) and not text[index].isspace() and text[index] not in "{}[](),:":
            index += 1
        word = text[start:index]
        if word in ("True", "False"):
            tokens.append(("literal", word == "True"))
        elif word == "None":
            tokens.append(("literal", None))
        else:
            try:
                tokens.append(("number", float(word) if any(c in word for c in ".eE") else int(word)))
            except ValueError:
                tokens.append(("symbol", word))
    return tokens


def _value(tokens, position):
    if position >= len(tokens):
        raise LibraryError("The CAE material data ended unexpectedly.")
    kind, value = tokens[position]
    if kind == "{" :
        result = {}
        position += 1
        while position < len(tokens) and tokens[position][0] != "}":
            key_kind, key = tokens[position]
            if key_kind not in ("string", "symbol"):
                raise LibraryError("The CAE material data has a non-text dictionary key.")
            if tokens[position + 1][0] != ":":
                raise LibraryError("The CAE material data is missing a colon.")
            item, position = _value(tokens, position + 2)
            result[key] = item
            if position < len(tokens) and tokens[position][0] == ",":
                position += 1
        return result, position + 1
    if kind in ("[", "("):
        closing = "]" if kind == "[" else ")"
        items = []
        position += 1
        while position < len(tokens) and tokens[position][0] != closing:
            item, position = _value(tokens, position)
            items.append(item)
            if position < len(tokens) and tokens[position][0] == ",":
                position += 1
        return (items if kind == "[" else tuple(items)), position + 1
    if kind == "symbol":
        return Symbol(value), position + 1
    return value, position + 1


def _unescape(text: str) -> str:
    """Decode a CAE text value, including CP932 escapes used by Japanese names."""
    if "\\" not in text:
        return text
    try:
        decoded = text.encode("latin-1", "backslashreplace").decode("unicode_escape")
        return decoded.encode("latin-1").decode("cp932")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _decode_value(value):
    if isinstance(value, str):
        return _unescape(value)
    if isinstance(value, dict):
        return {str(key): _decode_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_decode_value(item) for item in value]
    return value


def _jsonable(value):
    if isinstance(value, Symbol):
        return {"$symbol": str(value)}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and value != value:
        return None
    return value


# ------------------------------------------------------------------ records


@dataclass
class Card:
    key: str
    parent: int
    name: str
    visible: bool
    metadata: dict
    raw: bytes
    data: dict = field(default_factory=dict)
    data_error: str = ""

    @property
    def category(self) -> str:
        return str(self.metadata.get("Category", "") or "")

    def metadata_json(self) -> dict:
        return _jsonable(_decode_value(self.metadata))

    def fingerprint(self) -> str:
        return sha256(self.raw).hexdigest()

    def describe(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "parent": self.parent,
            "category": self.category,
            "fingerprint": self.fingerprint(),
            "metadata": self.metadata_json(),
            "data": _jsonable(self.data),
            "dataError": self.data_error,
        }


@dataclass
class Library:
    cards: list[Card]
    containers: list[dict]
    fingerprint: str
    size: int
    raw: bytes
    # Every top-level record's original byte span, in file order. The memo table
    # is shared across the stream, so an export must copy all of them.
    record_bytes: list[bytes] = field(default_factory=list)


def parse(data: bytes) -> Library:
    value, spans = _parse(data)
    if not isinstance(value, tuple):
        raise LibraryError("The library file does not contain a record tuple.")
    if len(spans) != len(value):
        raise LibraryError("The library file record spans could not be resolved.")
    if len(value) > MAX_RECORDS:
        raise LibraryError("The library file exceeds the 4096 record limit.")
    cards, containers, record_bytes = [], [], []
    for record, (start, end) in zip(value, spans):
        if not isinstance(record, tuple) or len(record) < 5:
            raise LibraryError("A library record does not have the expected five fields.")
        key, parent, name, visible, metadata = record[:5]
        if not isinstance(name, str) or not isinstance(metadata, dict):
            raise LibraryError("A library record has a malformed name or metadata block.")
        raw = data[start:end]
        record_id = str(key)
        if not raw.startswith(b"(") or not raw.endswith(b"t"):
            raise LibraryError("A library record could not be copied byte-for-byte.")
        record_bytes.append(raw)
        card = Card(
            key=record_id,
            parent=int(parent),
            name=_unescape(name),
            visible=bool(visible),
            metadata=metadata,
            raw=raw,
        )
        text = metadata.get("Data")
        if isinstance(text, str):
            try:
                parsed = _literal(_unescape(text))
                if not isinstance(parsed, dict):
                    raise LibraryError("The material data is not a dictionary.")
                card.data = parsed
            except LibraryError as exc:
                card.data_error = str(exc)
        if card.parent < 0:
            containers.append(card.describe())
            continue
        cards.append(card)
    if not cards:
        raise LibraryError("The library contains no material records.")
    return Library(
        cards=cards,
        containers=containers,
        fingerprint=sha256(data).hexdigest(),
        size=len(data),
        raw=data,
        record_bytes=record_bytes,
    )


def export_bytes(library: Library, keep: set[str] | None = None) -> bytes:
    """Return CAE's own bytes for the source library.

    The stream interleaves global memo definitions between record tuples, so
    reconstructing a subset would break later memo references. The faithful
    export is the original stream; ``keep`` only selects which registered cards
    are reported as current. A card whose registered values no longer match its
    source record is reported by the caller and is not presented as exported.
    """
    return library.raw


def _rows(block):
    """Numeric rows of a CAE table, in source column order."""
    table = (block or {}).get("table") or ()
    rows = []
    for row in table:
        if isinstance(row, (list, tuple)):
            try:
                rows.append([float(value) for value in row])
            except (TypeError, ValueError):
                raise LibraryError("A CAE material table contains a non-numeric value.")
    return rows


def _flag(value):
    return str(value) == "ON" if value is not None else False


def _temperature_dependent(*blocks):
    for block in blocks:
        if block and _flag(block.get("temperatureDependency")):
            return True
        if block and int(block.get("dependencies") or 0):
            return True
    return False


def assessment(card: Card) -> dict:
    """Registering is separate from running.

    Every well-formed record is registrable, with its source hierarchy, units,
    full property data, Japanese text and fingerprint. This function also reports
    whether the record can define a *new 2D implicit-dynamics run* as it stands:
    that additionally needs a density and a structural law this writer can emit
    without inventing values. Missing or unsupported inputs are named precisely
    and stay empty; they are never filled with a guess.
    """
    data = card.data or {}
    ignored = {"name", "materialIdentifier", "description"}
    laws = sorted(set(data) - ignored)
    result = {
        "key": card.key,
        "name": card.name,
        "law": laws,
        "registrable": False,
        "available": False,
        "model": None,
        "family": None,
        "family_hint": "polymer",
        "values": {},
        "density": None,
        "needs": [],
        "reasons": [],
        "properties": laws,
        "blocks": {},
        "source": data,
    }
    if card.data_error:
        result["reasons"].append({"code": "cae.data_unreadable", "detail": card.data_error})
        return result
    if not laws:
        result["reasons"].append({"code": "cae.no_material_data"})
        return result

    known = {
        "density",
        "elastic",
        "hyperfoam",
        "hyperelastic",
        "viscoelastic",
        "plastic",
        "mullinsEffect",
        "conductivity",
        "specificHeat",
        "creep",
        "rateDependent",
        "expansion",
        "permeability",
        "electricalConductivity",
        "porousElastic",
        "damping",
    }
    unknown = [name for name in laws if name not in known]
    for name in unknown:
        result["reasons"].append({"code": "cae.unknown_property", "property": name})
    for name, code in (
        ("creep", "cae.creep_unsupported"),
        ("rateDependent", "cae.rate_dependent_unsupported"),
        ("expansion", "cae.expansion_unsupported"),
    ):
        if name in data:
            result["reasons"].append({"code": code, "property": name})
    if unknown or any(
        code.endswith("_unsupported") for code in (item["code"] for item in result["reasons"])
    ):
        return result

    density_block = data.get("density") or {}
    density_rows = _rows(density_block) if density_block else []
    if _temperature_dependent(density_block) or (density_rows and len(density_rows[0]) > 1):
        result["reasons"].append({"code": "cae.temperature_dependent", "property": "density"})
    elif density_rows:
        try:
            density = float(density_rows[0][0])
        except (TypeError, ValueError):
            density = 0.0
        if density <= 0:
            result["reasons"].append({"code": "cae.density_invalid"})
        else:
            result["density"] = density
    else:
        result["needs"].append("density")

    structural = False
    elastic = data.get("elastic") or {}
    if elastic:
        block = elastic
        if str(block.get("type", "ISOTROPIC")) != "ISOTROPIC":
            result["reasons"].append({"code": "cae.elastic_not_isotropic"})
        if _temperature_dependent(block):
            result["reasons"].append({"code": "cae.temperature_dependent", "property": "elastic"})
        rows = _rows(block)
        if not rows or len(rows[0]) < 2:
            result["reasons"].append({"code": "cae.elastic_table_missing"})
        else:
            rows = [row[:2] for row in rows]
            if len(rows) > 1:
                result["reasons"].append(
                    {"code": "cae.multiple_elastic_rows", "property": "elastic"}
                )
            young, poisson = rows[0]
            if young <= 0 or not (-1 < poisson < 0.5):
                result["reasons"].append({"code": "cae.elastic_value_out_of_range"})
            else:
                structural = True
                result["elastic"] = {"young": young, "poisson": poisson}
                result["family_hint"] = "metal" if young >= 50000 else "polymer"

    foam = data.get("hyperfoam") or {}
    if foam:
        if _temperature_dependent(foam) or _temperature_dependent(foam.get("uniaxialTestData")):
            result["reasons"].append(
                {"code": "cae.temperature_dependent", "property": "hyperfoam"}
            )
        n = int(foam.get("n") or 1)
        test_data = _flag(foam.get("testData"))
        uniaxial_block = foam.get("uniaxialTestData") or {}
        lateral = _flag(uniaxial_block.get("lateralNominalStrain"))
        uniaxial = _rows(uniaxial_block)
        table = _rows(foam)
        poisson = foam.get("poisson")
        if not 1 <= n <= 6:
            result["reasons"].append({"code": "cae.hyperfoam_order", "n": n})
        elif test_data:
            if len(uniaxial) < 3:
                result["reasons"].append({"code": "cae.hyperfoam_test_data_missing"})
            else:
                if lateral:
                    keep = [row[:3] for row in uniaxial if len(row) >= 3]
                else:
                    # The source flag says no lateral strain was measured. Its
                    # third column is zero-filled storage, not data.
                    keep = [row[:2] for row in uniaxial if len(row) >= 2]
                result["blocks"]["hyperfoam"] = {
                    "n": n,
                    "test_data": True,
                    "moduli": str(foam.get("moduli") or "LONG_TERM"),
                    "lateral": lateral,
                    "poisson": None if poisson is None else float(poisson),
                    "table": [],
                    "uniaxial": keep,
                }
                structural = True
        else:
            if not table:
                result["reasons"].append({"code": "cae.hyperfoam_coefficients_missing"})
            elif any(len(row) != 3 * n for row in table):
                result["reasons"].append(
                    {
                        "code": "cae.hyperfoam_coefficients_shape",
                        "n": n,
                        "expected": 3 * n,
                        "found": len(table[0]),
                    }
                )
            else:
                result["blocks"]["hyperfoam"] = {
                    "n": n,
                    "test_data": False,
                    "moduli": str(foam.get("moduli") or "LONG_TERM"),
                    "lateral": lateral,
                    "poisson": None if poisson is None else float(poisson),
                    "table": table,
                    "uniaxial": [],
                }
                structural = True

    hyper = data.get("hyperelastic") or {}
    if hyper:
        if _temperature_dependent(hyper) or _temperature_dependent(hyper.get("uniaxialTestData")):
            result["reasons"].append(
                {"code": "cae.temperature_dependent", "property": "hyperelastic"}
            )
        law = str(hyper.get("type") or "")
        if law not in ("MARLOW", "YEOH", "OGDEN", "POLYNOMIAL", "NEO_HOOKE"):
            result["reasons"].append({"code": "cae.hyperelastic_type", "type": law})
        elif str(hyper.get("materialType", "ISOTROPIC")) != "ISOTROPIC":
            result["reasons"].append({"code": "cae.hyperelastic_not_isotropic"})
        else:
            n = int(hyper.get("n") or 1)
            test_data = _flag(hyper.get("testData"))
            uniaxial_block = hyper.get("uniaxialTestData") or {}
            lateral = _flag(uniaxial_block.get("lateralNominalStrain"))
            uniaxial = _rows(uniaxial_block)
            table = _rows(hyper)
            block = {
                "type": law,
                "n": n,
                "test_data": test_data,
                "moduli_time_scale": str(hyper.get("moduliTimeScale") or "LONG_TERM"),
                "lateral": lateral,
                "table": table,
                "uniaxial": (
                    [row[:3] if lateral else row[:2] for row in uniaxial]
                    if test_data
                    else []
                ),
            }
            result["blocks"]["hyperelastic"] = block
            structural = True

    visco = data.get("viscoelastic") or {}
    if visco:
        if _temperature_dependent(visco):
            result["reasons"].append(
                {"code": "cae.temperature_dependent", "property": "viscoelastic"}
            )
        if str(visco.get("domain", "TIME")) != "TIME" or str(visco.get("time", "PRONY")) not in (
            "PRONY",
            "CREEP",
            "RELAXATION",
        ):
            result["reasons"].append({"code": "cae.viscoelastic_options_unsupported"})
        else:
            table = _rows(visco)
            if any(len(row) != 3 for row in table):
                result["reasons"].append({"code": "cae.viscoelastic_table_shape"})
            elif table:
                result["blocks"]["viscoelastic"] = {
                    "domain": "TIME",
                    "time": str(visco.get("time") or "PRONY"),
                    "table": table,
                }

    plastic = data.get("plastic") or {}
    if plastic:
        if _temperature_dependent(plastic) or _flag(plastic.get("rate")):
            result["reasons"].append({"code": "cae.plastic_rate_unsupported"})
        elif str(plastic.get("hardening", "ISOTROPIC")) not in ("ISOTROPIC", "KINEMATIC"):
            result["reasons"].append(
                {"code": "cae.plastic_hardening_unsupported", "hardening": str(plastic.get("hardening"))}
            )
        else:
            table = _rows(plastic)
            if any(len(row) != 2 for row in table):
                result["reasons"].append({"code": "cae.plastic_table_shape"})
            elif table:
                result["blocks"]["plastic"] = {
                    "hardening": str(plastic.get("hardening") or "ISOTROPIC"),
                    "table": table,
                }
                structural = True

    mullins = data.get("mullinsEffect") or {}
    if mullins:
        if _temperature_dependent(mullins):
            result["reasons"].append(
                {"code": "cae.temperature_dependent", "property": "mullinsEffect"}
            )
        definition = str(mullins.get("definition") or "CONSTANTS")
        table = _rows(mullins)
        if definition != "CONSTANTS":
            result["reasons"].append(
                {"code": "cae.mullins_definition_unsupported", "definition": definition}
            )
        elif table:
            result["blocks"]["mullins"] = {"definition": "CONSTANTS", "table": table}

    thermal = {}
    conductivity = data.get("conductivity") or {}
    specific = data.get("specificHeat") or {}
    if conductivity or specific:
        if _temperature_dependent(conductivity, specific):
            result["reasons"].append({"code": "cae.temperature_dependent", "property": "thermal"})
        else:
            thermal = {
                "conductivity": _rows(conductivity),
                "specific_heat": _rows(specific),
            }
            if not thermal["conductivity"] and not thermal["specific_heat"]:
                thermal = {}
            else:
                result["blocks"]["thermal"] = thermal

    if not structural:
        result["needs"].append("structural_law")
        # A thermal-only record is still registered for browsing and export; it
        # simply cannot define this structural procedure until a law is added.
        if not thermal:
            result["reasons"].append({"code": "cae.no_structural_law"})
    if result["reasons"]:
        return result

    result["registrable"] = True
    result["family_hint"] = result.get("family_hint") or "polymer"
    # Pure isotropic elasticity with a density is the historical simplified law;
    # it stays on that path so existing PA6/METAL pins and editor behaviour are
    # preserved. Every other combination is a faithful registered CAE card.
    if (
        set(laws) <= {"density", "elastic"}
        and result["density"] is not None
        and result.get("elastic")
    ):
        result["model"] = "linear_elastic"
        result["values"] = {
            "young": result["elastic"]["young"],
            "poisson": result["elastic"]["poisson"],
            "density": result["density"],
        }
    else:
        result["model"] = "cae_law"
    result["available"] = result["model"] is not None and not result["needs"]
    return result


def eligibility(card: Card) -> dict:
    """Backward-compatible view of :func:`assessment`.

    ``eligible`` keeps its historical meaning: usable by a new run without
    changing behaviour. It is no longer the registration decision.
    """
    decision = assessment(card)
    return {
        **decision,
        "eligible": decision["available"],
        "reasons": decision["reasons"],
        "values": decision["values"],
    }


def write_export(library: Library, path, keep: set[str] | None = None) -> dict:
    """Write the CAE-readable stream and verify it parses back before publishing."""
    content = export_bytes(library, keep)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(content)
    try:
        reparsed = parse(content)
    except LibraryError:
        temporary.unlink(missing_ok=True)
        raise
    if len(reparsed.cards) != len(library.cards) or reparsed.fingerprint != library.fingerprint:
        temporary.unlink(missing_ok=True)
        raise LibraryError("The exported library did not round-trip to the same records.")
    temporary.replace(path)
    return {
        "path": str(path),
        "bytes": len(content),
        "sha256": sha256(content).hexdigest(),
        "cards": [card.name for card in reparsed.cards],
    }
