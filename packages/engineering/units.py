"""Drawing unit policy: normalize imported world geometry to millimetres once.

The project geometry convention is millimetres. Every reader (native DXF, the
DWG inventory and any converted fallback) asks this module for one
interpretation and applies it exactly once, before geometry reconstruction,
tolerance checks, display, meshing, picking or partitioning. The saved model is
always in mm; the source bytes and downloaded originals keep their own units.

The policy follows the source-format unit enumeration used by both DXF
``$INSUNITS`` and the DWG decoder (ACadSharp ``UnitsType``), including the
international and US survey definitions. It records the original declaration,
the numeric mm factor and where the assumption came from next to the source
digest, so a reopen, duplicate or DWG translation can never scale twice.

* a drawing header that declares millimetres imports directly;
* any other recognised unit is converted once and recorded;
* an explicit unitless header is interpreted as project millimetres;
* a missing header is recorded separately from a valid unitless header;
* an unreadable code, contradictory metadata or a converted coordinate outside
  the project range is reported with the specific issue. Scale is never guessed
  and coordinates are never silently clamped.
"""

from dataclasses import dataclass
import math

from .model import Source

DECLARED_MM = "declared_mm"
CONVERTED_TO_MM = "converted_to_mm"
UNITLESS_AS_MM = "unitless_as_mm"
HEADER_MISSING_AS_MM = "header_missing_as_mm"

UNITLESS_NOTE = "unitless drawing interpreted as mm"
MISSING_NOTE = "unit header missing; interpreted as mm"
MAX_COORDINATE_MM = 1e6
# Stored project geometry resolution. The conversion removes floating-point
# residue far below any CAD or engineering tolerance (1e-9 mm = 1 pm) so a
# boundary that physically lies on 10 mm does not become 10.000000000000002 and
# change a mesh division count. This is normalization of the conversion result,
# never a clamp of out-of-range or unreadable input.
GEOMETRY_RESOLUTION_MM = 1e-9


@dataclass(frozen=True)
class UnitDefinition:
    """One enumerable CAD length unit and its millimetre factor."""

    code: int
    canonical: str
    factor: float
    aliases: tuple[str, ...] = ()

    @property
    def is_metric(self):
        return self.code in {4, 5, 6, 7, 12, 13, 14, 15, 16, 17}


_US_SURVEY_FOOT = 1200.0 / 3937.0 * 1000.0
_UNITS = (
    UnitDefinition(0, "unitless", 1.0, ("none", "no unit", "no units")),
    UnitDefinition(1, "inches", 25.4, ("inch", "in", '"', "inch (international)")),
    UnitDefinition(2, "feet", 304.8, ("foot", "ft", "'")),
    UnitDefinition(3, "miles", 1609344.0, ("mile", "mi")),
    UnitDefinition(4, "millimetres", 1.0, ("millimeter", "millimeters", "millimetre", "mm")),
    UnitDefinition(5, "centimetres", 10.0, ("centimeter", "centimeters", "centimetre", "cm")),
    UnitDefinition(6, "metres", 1000.0, ("meter", "meters", "metre", "m")),
    UnitDefinition(7, "kilometres", 1e6, ("kilometer", "kilometers", "kilometre", "km")),
    UnitDefinition(8, "microinches", 2.54e-5, ("microinch",)),
    UnitDefinition(9, "mils", 0.0254, ("mil",)),
    UnitDefinition(10, "yards", 914.4, ("yard", "yd")),
    UnitDefinition(11, "angstroms", 1e-7, ("angstrom", "ångström", "angstroms", "å")),
    UnitDefinition(12, "nanometres", 1e-6, ("nanometer", "nanometers", "nanometre", "nm")),
    UnitDefinition(
        13, "microns", 1e-3, ("micron", "micrometer", "micrometers", "micrometre", "µm", "μm")
    ),
    UnitDefinition(14, "decimetres", 100.0, ("decimeter", "decimeters", "decimetre", "dm")),
    UnitDefinition(15, "decametres", 10000.0, ("decameter", "decameters", "decametre", "dam")),
    UnitDefinition(16, "hectometres", 100000.0, ("hectometer", "hectometers", "hectometre", "hm")),
    UnitDefinition(17, "gigametres", 1e12, ("gigameter", "gigameters", "gigametre", "gm")),
    UnitDefinition(
        18, "astronomical units", 1.495978707e14, ("astronomical unit", "au", "astro")
    ),
    UnitDefinition(19, "light years", 9.4607304725808e18, ("light year", "ly", "lightyears")),
    UnitDefinition(20, "parsecs", 3.0856775814913673e19, ("parsec", "pc")),
    UnitDefinition(
        21,
        "US survey feet",
        _US_SURVEY_FOOT,
        ("us survey foot", "us survey feet", "ussurveyfeet", "usft", "survey foot", "survey feet"),
    ),
    UnitDefinition(
        22,
        "US survey inch",
        _US_SURVEY_FOOT / 12.0,
        ("us survey inch", "ussurveyinch", "survey inch"),
    ),
    UnitDefinition(
        23,
        "US survey yard",
        _US_SURVEY_FOOT * 3.0,
        ("us survey yard", "ussurveyyard", "survey yard"),
    ),
    UnitDefinition(
        24,
        "US survey mile",
        _US_SURVEY_FOOT * 5280.0,
        ("us survey mile", "ussurveymile", "survey mile"),
    ),
)

_BY_CODE = {unit.code: unit for unit in _UNITS}
_BY_NAME = {
    alias.casefold(): unit for unit in _UNITS for alias in (unit.canonical, *unit.aliases)
}

# ``$MEASUREMENT``: 0 = imperial drawing, 1 = metric drawing.
_MEASUREMENT_NAMES = {0: "imperial", 1: "metric"}


@dataclass(frozen=True)
class Interpretation:
    """The one recorded decision about a drawing's declared length unit."""

    basis: str
    note: str
    declaration: str
    factor: float
    provenance: str
    warning: str = ""

    def __iter__(self):
        # Tuple compatibility for callers that only need (basis, note).
        yield self.basis
        yield self.note

    def apply(self, value, label=""):
        """Convert one drawing length to project millimetres with a range check."""
        try:
            converted = float(value) * self.factor
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label or 'The drawing'} has a non-numeric length.") from exc
        if not math.isfinite(converted):
            raise ValueError(f"{label or 'The drawing'} has a non-finite length after unit conversion.")
        if abs(converted) > MAX_COORDINATE_MM:
            raise ValueError(
                f"{label or 'The drawing'} converts to {converted:.6g} mm, outside the "
                f"supported +/-{MAX_COORDINATE_MM:.0f} mm project range. Check the declared "
                "drawing unit instead of rescaling silently."
            )
        return round(converted, 9)

    def point(self, value, label=""):
        return tuple(self.apply(component, label) for component in value)


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
            return text.casefold()
    return value


def _measurement_flag(value):
    code = _code(value)
    if isinstance(code, int) and code in _MEASUREMENT_NAMES:
        return code
    return None


def interpret(value, source="drawing", measurement=None):
    """Return an :class:`Interpretation` for a drawing's declared unit header.

    Raises ``ValueError`` naming the declared unit for an unreadable unit, for
    contradictory metric/imperial metadata and for a converted length outside
    the project range. The caller applies ``interpretation.factor`` exactly once.
    """
    code = _code(value)
    if code is None:
        return Interpretation(
            HEADER_MISSING_AS_MM, MISSING_NOTE, "missing", 1.0, "no unit header"
        )
    if code == 0 or code == "unitless" or code == "none":
        return Interpretation(
            UNITLESS_AS_MM, UNITLESS_NOTE, "unitless", 1.0, "explicit unitless header"
        )
    unit = _BY_CODE.get(code) if isinstance(code, int) else _BY_NAME.get(code)
    if unit is None:
        if isinstance(code, int):
            raise ValueError(
                f"The {source} header declares an unreadable drawing unit code {code}. "
                "Set the drawing units to a recognised unit (for example millimetres) before importing."
            )
        raise ValueError(
            f"The {source} declares the unknown drawing unit '{value}'. Use a recognised unit "
            "name or code before importing."
        )
    measurement_code = _measurement_flag(measurement)
    warning = ""
    if measurement_code == 1 and not unit.is_metric and unit.code != 0:
        # Contradictory metadata is reported with the specific issue. The unit
        # header itself is authoritative for the factor; the drawing is not
        # rejected or rescaled because $MEASUREMENT is frequently stale.
        warning = (
            f"metadata inconsistency: the unit header declares {unit.canonical} while "
            "$MEASUREMENT declares a metric drawing; the unit header was used"
        )
    if unit.code == 4:
        return Interpretation(
            DECLARED_MM,
            f"millimetres (declared in the {source} header)",
            "millimetres",
            1.0,
            f"{source} unit code 4" + ("; " + warning if warning else ""),
            warning,
        )
    note = (
        f"declared {unit.canonical}; converted to mm (factor {unit.factor:.12g})"
    )
    return Interpretation(
        CONVERTED_TO_MM,
        note,
        unit.canonical,
        unit.factor,
        f"{source} unit code {unit.code}" + ("; " + warning if warning else ""),
        warning,
    )


def record(interpretation, source: Source) -> Source:
    """Attach the recorded interpretation to a source block (already copied)."""
    source.drawing_units = interpretation.note
    source.unit_basis = interpretation.basis
    source.unit_declaration = interpretation.declaration
    source.unit_factor = interpretation.factor
    source.unit_provenance = interpretation.provenance
    return source


def factor(value, source="drawing", measurement=None):
    """Convenience: the numeric millimetre factor for a declared unit."""
    return interpret(value, source, measurement).factor
