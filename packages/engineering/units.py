"""Drawing unit policy for imported sections.

The project geometry convention is millimetres. The policy is deliberately
narrow and explicit:

* a drawing header that declares millimetres imports directly;
* an explicit unitless header is interpreted as project millimetres and is
  recorded as ``unitless drawing interpreted as mm`` - nobody is asked to
  "confirm" it;
* a missing header is recorded separately from a valid unitless header;
* any other declared unit is rejected with a message that names the unit. No
  drawing is silently reinterpreted from inches (or any other unit).
"""

DECLARED_MM = "declared_mm"
UNITLESS_AS_MM = "unitless_as_mm"
HEADER_MISSING_AS_MM = "header_missing_as_mm"

UNITLESS_NOTE = "unitless drawing interpreted as mm"
MISSING_NOTE = "unit header missing; interpreted as mm"

_NAMES = {
    0: "unitless",
    1: "inches",
    2: "feet",
    3: "miles",
    4: "millimetres",
    5: "centimetres",
    6: "metres",
    7: "kilometres",
    8: "microinches",
    9: "mils",
    10: "yards",
    11: "angstroms",
    12: "nanometres",
    13: "microns",
    14: "decimetres",
    15: "decametres",
    16: "hectometres",
    17: "gigametres",
}


def _code(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return text.lower()
    return value


def interpret(value, source="drawing"):
    """Return ``(basis, note)`` for a drawing's declared unit header.

    Raises ``ValueError`` naming the declared unit for an unsupported unit and
    a distinct error for a header that cannot be read at all.
    """
    code = _code(value)
    if code is None:
        return HEADER_MISSING_AS_MM, MISSING_NOTE
    if code == 0 or code == "unitless":
        return UNITLESS_AS_MM, UNITLESS_NOTE
    if code == 4 or code in {"millimeters", "millimetres", "mm"}:
        return DECLARED_MM, f"millimetres (declared in the {source} header)"
    if isinstance(code, int) and code not in _NAMES:
        raise ValueError(
            f"The {source} header declares an unreadable drawing unit code {code}. "
            "Set the drawing units to millimetres before importing."
        )
    name = _NAMES.get(code, code) if isinstance(code, int) else code
    raise ValueError(
        f"The drawing declares {name} instead of millimetres. Convert it to millimetres "
        "before importing; inches are never silently reinterpreted as millimetres."
    )
