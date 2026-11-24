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


def eligibility(card: Card) -> dict:
    """Decide whether a CAE card can be used without changing its behaviour.

    Only a pure isotropic linear-elastic card with a constant density maps onto
    an application law exactly. Every other law is reported with a precise reason
    and stays visible but ineligible: a generic or approximate translation would
    silently change the material response.
    """
    data = card.data or {}
    ignored = {"name", "materialIdentifier", "description"}
    laws = sorted(set(data) - ignored)
    result = {
        "key": card.key,
        "name": card.name,
        "law": laws,
        "eligible": False,
        "model": None,
        "family": None,
        "values": {},
        "reasons": [],
        "properties": laws,
    }
    if card.data_error:
        result["reasons"].append({"code": "cae.data_unreadable", "detail": card.data_error})
        return result
    if not laws:
        result["reasons"].append({"code": "cae.no_material_data"})
        return result
    for key, code in (
        ("hyperelastic", "cae.hyperelastic_unsupported"),
        ("hyperfoam", "cae.hyperfoam_unsupported"),
        ("plastic", "cae.plasticity_unsupported"),
        ("viscoelastic", "cae.viscoelasticity_unsupported"),
        ("mullinsEffect", "cae.mullins_unsupported"),
        ("creep", "cae.creep_unsupported"),
        ("rateDependent", "cae.rate_dependent_unsupported"),
    ):
        if key in data:
            result["reasons"].append({"code": code, "property": key})
    if "elastic" not in data:
        if not result["reasons"]:
            result["reasons"].append({"code": "cae.no_structural_law"})
        return result
    elastic = data.get("elastic") or {}
    if str(elastic.get("type", "")) != "ISOTROPIC":
        result["reasons"].append({"code": "cae.elastic_not_isotropic"})
    if isinstance(elastic.get("temperatureDependency"), Symbol) and str(
        elastic.get("temperatureDependency")
    ) == "ON":
        result["reasons"].append({"code": "cae.temperature_dependent"})
    if int(elastic.get("dependencies") or 0) != 0:
        result["reasons"].append({"code": "cae.field_dependent"})
    table = elastic.get("table") or []
    if not table or not isinstance(table[0], (list, tuple)) or len(table[0]) < 2:
        result["reasons"].append({"code": "cae.elastic_table_missing"})
    density_block = data.get("density") or {}
    density_table = density_block.get("table") or []
    if not density_table or not isinstance(density_table[0], (list, tuple)):
        result["reasons"].append({"code": "cae.density_missing"})
    if result["reasons"]:
        return result
    try:
        young = float(table[0][0])
        poisson = float(table[0][1])
        density = float(density_table[0][0])
    except (TypeError, ValueError):
        result["reasons"].append({"code": "cae.elastic_table_missing"})
        return result
    if young <= 0 or density <= 0 or not (-1 < poisson < 0.5):
        result["reasons"].append({"code": "cae.elastic_value_out_of_range"})
        return result
    result.update(
        {
            "eligible": True,
            "model": "linear_elastic",
            "values": {"young": young, "poisson": poisson, "density": density},
        }
    )
    return result


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
