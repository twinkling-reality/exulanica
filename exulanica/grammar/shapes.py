"""Record shapes: every field of a record kind declared once, as data, and one validator for all.

A grammar with dozens of record kinds cannot keep a hand-written validator, a hand-written
reader and a hand-written TypeScript mirror in step. So each kind declares a
:class:`RecordShape`: its fields in dataclass order, each with a kind, its bounds, its closed
values, the record kinds an identity may refer to and the catalog a key resolves in. Everything
else reads the shape:

* :func:`validate_record` checks an instance field by field, then the shape's named rules;
* :func:`read_record` turns a ``record_payload`` back into an instance, refusing a missing or an
  unknown field at any depth;
* :func:`describe_shapes` writes the table as plain JSON-ready data, so a reader in another
  language compares itself with the shapes rather than with a transcription;
* :func:`index_records`, :func:`check_references`, :func:`check_identities` and
  :func:`check_vocabularies` check a set of records against each other.

**Refusal order.** :func:`validate_record` first puts the whole record through canonical JSON,
so a float anywhere raises ``CanonicalisationError`` before any field check runs, and ``None``,
``bool``, lists and mappings raise ``InvalidRecordError``. Only then do the field checks run.

**Identity rules.** A shape may declare how its own identity is derived, by
:func:`exulanica.grammar.subjects.subject_identity`: from the field that names its owner (or from
the generation's root when there is none) and from an ordinal, which is a field, a fixed number,
or a fixed code looked up from a field. :func:`check_identities` recomputes every one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.contract import ADMISSIBLE_USES, PLANE, DeclaredSemantics
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.geometry import Extent, require_ring
from exulanica.grammar.parameters import ParameterBinding
from exulanica.grammar.records import (
    MAX_SAFE_INTEGER,
    require_hex64,
    require_identity,
    require_integer,
    require_key,
    require_record,
    require_text,
)
from exulanica.grammar.seed import require_seed
from exulanica.grammar.subjects import subject_identity
from exulanica.grammar.textures import TEXTURE_SET_ID

__all__ = [
    "EXTENT_SHAPE",
    "FIELD_KINDS",
    "PARAMETER_BINDING_SHAPE",
    "SEMANTICS_SHAPE",
    "FieldShape",
    "IdentityRule",
    "RecordRule",
    "RecordShape",
    "check_identities",
    "check_references",
    "check_vocabularies",
    "choice",
    "choices",
    "describe_shapes",
    "hex64",
    "identities",
    "identity",
    "index_records",
    "integer",
    "integers",
    "key",
    "keys",
    "optional_identity",
    "optional_record",
    "optional_text",
    "points",
    "read_record",
    "record",
    "records",
    "ring",
    "rings",
    "scalar",
    "seed",
    "text",
    "texture_set_id",
    "validate_record",
]

FIELD_KINDS: Final = (
    "integer",
    "key",
    "choice",
    "text",
    "identity",
    "hex64",
    "seed",
    "texture_set_id",
    "scalar",
    "integers",
    "keys",
    "choices",
    "identities",
    "texts",
    "points",
    "ring",
    "rings",
    "record",
    "records",
)

_SEQUENCE_KINDS: Final = frozenset(
    {"integers", "keys", "choices", "identities", "texts", "points", "rings", "records"}
)
#: Kinds whose count bounds mean something: sequence lengths, or a ring's vertex count.
_COUNTED_KINDS: Final = _SEQUENCE_KINDS | {"ring"}


@dataclass(frozen=True, slots=True)
class FieldShape:
    """One field of a record kind. Unused attributes keep their neutral values."""

    name: str
    kind: str
    minimum: int | None = None
    maximum: int | None = None
    values: tuple[str, ...] = ()
    count_minimum: int = 0
    count_maximum: int | None = None
    increasing: bool = False
    dimension: int = 0
    shape: RecordShape | None = None
    refers_to: tuple[str, ...] = ()
    vocabulary: str = ""

    def __post_init__(self) -> None:
        require_key("a field name", self.name)
        if self.kind not in FIELD_KINDS:
            raise InvalidRecordError(f"{self.name}: field kind {self.kind!r} is unknown")
        if (self.kind in ("record", "records")) != (self.shape is not None):
            raise InvalidRecordError(f"{self.name}: a nested shape goes with record kinds only")
        if (self.kind in ("choice", "choices")) != bool(self.values):
            raise InvalidRecordError(f"{self.name}: closed values go with choice kinds only")
        if self.kind == "points" and self.dimension not in (2, 3):
            raise InvalidRecordError(f"{self.name}: points have dimension 2 or 3")
        if self.refers_to and self.kind not in ("identity", "identities"):
            raise InvalidRecordError(f"{self.name}: only an identity refers to a record")
        if self.vocabulary and self.kind not in ("key", "keys"):
            raise InvalidRecordError(f"{self.name}: only a key resolves in a vocabulary")
        if self.kind not in _COUNTED_KINDS and (self.count_minimum or self.count_maximum):
            raise InvalidRecordError(f"{self.name}: counts go with sequence kinds only")
        if (self.minimum is not None or self.maximum is not None) and self.kind not in (
            "integer",
            "integers",
        ):
            raise InvalidRecordError(f"{self.name}: integer bounds go with integer kinds only")

    def describe(self) -> dict[str, object]:
        described: dict[str, object] = {"name": self.name, "kind": self.kind}
        if self.minimum is not None:
            described["minimum"] = self.minimum
        if self.maximum is not None:
            described["maximum"] = self.maximum
        if self.values:
            described["values"] = list(self.values)
        if self.kind in _COUNTED_KINDS:
            described["count_minimum"] = self.count_minimum
            if self.count_maximum is not None:
                described["count_maximum"] = self.count_maximum
        if self.increasing:
            described["increasing"] = "strictly"
        if self.dimension:
            described["dimension"] = self.dimension
        if self.shape is not None:
            described["shape"] = self.shape.name
        if self.refers_to:
            described["refers_to"] = list(self.refers_to)
        if self.vocabulary:
            described["vocabulary"] = self.vocabulary
        return described


@dataclass(frozen=True, slots=True)
class RecordRule:
    """A named check across a record's fields, for what no single field can state."""

    name: str
    check: Callable[[Any], None]


@dataclass(frozen=True, slots=True)
class IdentityRule:
    """How a record's own identity is derived from its owner and its ordinal.

    ``owner_field`` names the field that holds the owner's identity; empty means the root of
    the generation owns it. The ordinal is ``ordinal_field``'s value, or
    ``ordinal_codes[record.<ordinal_field>]`` when codes are given, or ``ordinal_constant``
    when no field is named.
    """

    subject_kind: str
    owner_field: str = ""
    ordinal_field: str = ""
    ordinal_codes: Mapping[str, int] | None = None
    ordinal_constant: int = 0
    field: str = "identity"

    def ordinal(self, record: object) -> int:
        if not self.ordinal_field:
            return self.ordinal_constant
        value = getattr(record, self.ordinal_field)
        if self.ordinal_codes is None:
            return value  # type: ignore[no-any-return]
        if value not in self.ordinal_codes:
            raise InvalidRecordError(f"{self.ordinal_field} {value!r} has no identity code")
        return self.ordinal_codes[value]

    def describe(self) -> dict[str, object]:
        described: dict[str, object] = {
            "field": self.field,
            "subject_kind": self.subject_kind,
            "owner_field": self.owner_field or "(root)",
        }
        if not self.ordinal_field:
            described["ordinal"] = self.ordinal_constant
        elif self.ordinal_codes is None:
            described["ordinal"] = self.ordinal_field
        else:
            described["ordinal"] = {
                "field": self.ordinal_field,
                "codes": dict(sorted(self.ordinal_codes.items())),
            }
        return described


@dataclass(frozen=True, slots=True)
class RecordShape:
    """A record kind: its dataclass, its fields in order, its rules, identity and extent."""

    record_type: type
    fields: tuple[FieldShape, ...]
    rules: tuple[RecordRule, ...] = ()
    identity: IdentityRule | None = None
    extent_field: str = ""

    def __post_init__(self) -> None:
        if not dataclasses.is_dataclass(self.record_type):
            raise InvalidRecordError(f"{self.record_type!r} is not a dataclass")
        declared = [field.name for field in dataclasses.fields(self.record_type)]
        shaped = [field.name for field in self.fields]
        if declared != shaped:
            raise InvalidRecordError(
                f"{self.name}: shape fields {shaped} are not the dataclass fields {declared}"
            )
        kind = getattr(self.record_type, "RECORD_KIND", None)
        version = getattr(self.record_type, "RECORD_VERSION", None)
        if (kind is None) != (version is None):
            raise InvalidRecordError(f"{self.name} declares only half of kind and version")
        names = [rule.name for rule in self.rules]
        if len(set(names)) != len(names):
            raise InvalidRecordError(f"{self.name} repeats a rule name")
        by_name = {field.name: field for field in self.fields}
        if self.identity is not None:
            own = by_name.get(self.identity.field)
            if own is None or own.kind != "identity":
                raise InvalidRecordError(f"{self.name}: its identity field is an identity")
            require_key("subject_kind", self.identity.subject_kind)
            if self.identity.owner_field:
                owner = by_name.get(self.identity.owner_field)
                if owner is None or owner.kind != "identity":
                    raise InvalidRecordError(f"{self.name}: its owner field is an identity")
            if self.identity.ordinal_field and self.identity.ordinal_field not in by_name:
                raise InvalidRecordError(f"{self.name}: its ordinal field does not exist")
        if self.extent_field:
            extent = by_name.get(self.extent_field)
            if extent is None or extent.kind != "record" or extent.shape is not EXTENT_SHAPE:
                raise InvalidRecordError(f"{self.name}: its extent field is an Extent")

    @property
    def kind(self) -> str:
        return getattr(self.record_type, "RECORD_KIND", "")

    @property
    def version(self) -> int:
        return getattr(self.record_type, "RECORD_VERSION", 0)

    @property
    def name(self) -> str:
        return self.kind or self.record_type.__name__

    def field(self, name: str) -> FieldShape:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        raise InvalidRecordError(f"{self.name} has no field {name!r}")

    def describe(self) -> dict[str, object]:
        described: dict[str, object] = {
            "shape": self.name,
            "fields": [field.describe() for field in self.fields],
            "rules": [rule.name for rule in self.rules],
        }
        if self.kind:
            described["kind"] = self.kind
            described["version"] = self.version
        if self.identity is not None:
            described["identity"] = self.identity.describe()
        if self.extent_field:
            described["extent_field"] = self.extent_field
        return described


# -------------------------------------------------------------------------------------------
# Field constructors, used as ``shapes.integer("x_mm")`` so the names read as a table.


def integer(name: str, minimum: int | None = None, maximum: int | None = None) -> FieldShape:
    return FieldShape(name, "integer", minimum=minimum, maximum=maximum)


def key(name: str, vocabulary: str = "") -> FieldShape:
    return FieldShape(name, "key", vocabulary=vocabulary)


def choice(name: str, values: Sequence[str]) -> FieldShape:
    return FieldShape(name, "choice", values=tuple(values))


def text(name: str) -> FieldShape:
    return FieldShape(name, "text")


def optional_text(name: str) -> FieldShape:
    return FieldShape(name, "texts", count_maximum=1)


def identity(name: str, *refers_to: str) -> FieldShape:
    return FieldShape(name, "identity", refers_to=refers_to)


def optional_identity(name: str, *refers_to: str) -> FieldShape:
    return FieldShape(name, "identities", count_maximum=1, refers_to=refers_to)


def identities(name: str, *refers_to: str, count_minimum: int = 0) -> FieldShape:
    return FieldShape(name, "identities", count_minimum=count_minimum, refers_to=refers_to)


def hex64(name: str) -> FieldShape:
    return FieldShape(name, "hex64")


def seed(name: str) -> FieldShape:
    return FieldShape(name, "seed")


def texture_set_id(name: str) -> FieldShape:
    return FieldShape(name, "texture_set_id")


def scalar(name: str) -> FieldShape:
    return FieldShape(name, "scalar")


def integers(
    name: str,
    minimum: int | None = None,
    maximum: int | None = None,
    *,
    increasing: bool = False,
    count_minimum: int = 0,
    count_maximum: int | None = None,
) -> FieldShape:
    return FieldShape(
        name,
        "integers",
        minimum=minimum,
        maximum=maximum,
        increasing=increasing,
        count_minimum=count_minimum,
        count_maximum=count_maximum,
    )


def keys(
    name: str, vocabulary: str = "", *, count_minimum: int = 0, count_maximum: int | None = None
) -> FieldShape:
    return FieldShape(
        name,
        "keys",
        vocabulary=vocabulary,
        count_minimum=count_minimum,
        count_maximum=count_maximum,
    )


def choices(name: str, values: Sequence[str], *, count_minimum: int = 0) -> FieldShape:
    return FieldShape(name, "choices", values=tuple(values), count_minimum=count_minimum)


def points(
    name: str, dimension: int, *, count_minimum: int = 1, count_maximum: int | None = None
) -> FieldShape:
    return FieldShape(
        name,
        "points",
        dimension=dimension,
        count_minimum=count_minimum,
        count_maximum=count_maximum,
    )


def ring(name: str, *, count_minimum: int = 3, count_maximum: int | None = None) -> FieldShape:
    """A simple counter-clockwise ring; the counts bound its number of vertices."""
    return FieldShape(name, "ring", count_minimum=count_minimum, count_maximum=count_maximum)


def rings(name: str) -> FieldShape:
    return FieldShape(name, "rings")


def record(name: str, shape: RecordShape) -> FieldShape:
    return FieldShape(name, "record", shape=shape)


def optional_record(name: str, shape: RecordShape) -> FieldShape:
    return FieldShape(name, "records", shape=shape, count_maximum=1)


def records(
    name: str,
    shape: RecordShape,
    *,
    count_minimum: int = 0,
    count_maximum: int | None = None,
) -> FieldShape:
    return FieldShape(
        name,
        "records",
        shape=shape,
        count_minimum=count_minimum,
        count_maximum=count_maximum,
    )


# -------------------------------------------------------------------------------------------
# Generic nested shapes


def _extent_ordered(extent: Extent) -> None:
    for axis in ("x", "y", "z"):
        if getattr(extent, f"min_{axis}_mm") > getattr(extent, f"max_{axis}_mm"):
            raise InvalidRecordError(f"extent: min_{axis}_mm is above max_{axis}_mm")


EXTENT_SHAPE: Final = RecordShape(
    Extent,
    tuple(integer(f"{corner}_{axis}_mm") for corner in ("min", "max") for axis in ("x", "y", "z")),
    rules=(RecordRule("extent_corners_ordered", _extent_ordered),),
)


def _semantics_plane(semantics: DeclaredSemantics) -> None:
    if semantics.plane != PLANE:
        raise InvalidRecordError(f"declared semantics name the {PLANE!r} plane")


SEMANTICS_SHAPE: Final = RecordShape(
    DeclaredSemantics,
    (
        key("subject_kind"),
        choices("admissible_uses", ADMISSIBLE_USES),
        choice("plane", (PLANE,)),
    ),
    rules=(RecordRule("semantics_plane_invented", _semantics_plane),),
)

PARAMETER_BINDING_SHAPE: Final = RecordShape(
    ParameterBinding,
    (key("name"), scalar("value"), key("source")),
)


# -------------------------------------------------------------------------------------------
# Validation


def validate_record(candidate: object, shape: RecordShape) -> Any:
    """``candidate`` is exactly the shape's type, canonical, and every field and rule holds."""
    record = require_record(candidate, shape.record_type)
    for field_shape in shape.fields:
        _check_field(field_shape, getattr(record, field_shape.name), shape.name)
    for rule in shape.rules:
        rule.check(record)
    return record


def _count(name: str, value: object, field_shape: FieldShape) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise InvalidRecordError(f"{name} is a tuple")
    if len(value) < field_shape.count_minimum:
        raise InvalidRecordError(f"{name} holds at least {field_shape.count_minimum}")
    if field_shape.count_maximum is not None and len(value) > field_shape.count_maximum:
        raise InvalidRecordError(f"{name} holds at most {field_shape.count_maximum}")
    return value


def _distinct(name: str, value: tuple[Any, ...]) -> None:
    if len(set(value)) != len(value):
        raise InvalidRecordError(f"{name} repeats an item")


def _check_field(field_shape: FieldShape, value: object, where: str) -> None:
    name = f"{where}.{field_shape.name}"
    kind = field_shape.kind
    if kind == "integer":
        require_integer(name, value, minimum=field_shape.minimum, maximum=field_shape.maximum)
    elif kind == "key":
        require_key(name, value)
    elif kind == "choice":
        if type(value) is not str or value not in field_shape.values:
            raise InvalidRecordError(f"{name} is one of {field_shape.values}, got {value!r}")
    elif kind == "text":
        require_text(name, value)
    elif kind == "identity":
        require_identity(name, value)
    elif kind == "hex64":
        require_hex64(name, value)
    elif kind == "seed":
        require_seed(value)
    elif kind == "texture_set_id":
        if type(value) is not str or TEXTURE_SET_ID.fullmatch(value) is None:
            raise InvalidRecordError(f"{name} is a texture set id, got {value!r}")
    elif kind == "scalar":
        if type(value) is int:
            require_integer(name, value, minimum=-MAX_SAFE_INTEGER, maximum=MAX_SAFE_INTEGER)
        elif type(value) is str:
            require_key(name, value)
        else:
            raise InvalidRecordError(f"{name} is an int or a key, got {type(value).__name__}")
    elif kind == "ring":
        ring_value = require_ring(name, value, minimum_count=max(3, field_shape.count_minimum))
        if field_shape.count_maximum is not None and len(ring_value) > field_shape.count_maximum:
            raise InvalidRecordError(f"{name} has at most {field_shape.count_maximum} vertices")
    elif kind == "record":
        assert field_shape.shape is not None
        if type(value) is not field_shape.shape.record_type:
            raise InvalidRecordError(f"{name} is a {field_shape.shape.name}")
        validate_record(value, field_shape.shape)
    else:
        _check_sequence(field_shape, name, _count(name, value, field_shape))


def _check_sequence(field_shape: FieldShape, name: str, items: tuple[Any, ...]) -> None:
    kind = field_shape.kind
    for index, item in enumerate(items):
        where = f"{name}[{index}]"
        if kind == "integers":
            require_integer(where, item, minimum=field_shape.minimum, maximum=field_shape.maximum)
            if field_shape.increasing and index and item <= items[index - 1]:
                raise InvalidRecordError(f"{name} is strictly increasing")
        elif kind == "keys":
            require_key(where, item)
        elif kind == "choices":
            if type(item) is not str or item not in field_shape.values:
                raise InvalidRecordError(f"{where} is one of {field_shape.values}")
        elif kind == "identities":
            require_identity(where, item)
        elif kind == "texts":
            require_text(where, item)
        elif kind == "points":
            if not isinstance(item, tuple) or len(item) != field_shape.dimension:
                raise InvalidRecordError(f"{where} has {field_shape.dimension} coordinates")
            for axis, coordinate in enumerate(item):
                require_integer(f"{where}[{axis}]", coordinate)
        elif kind == "rings":
            require_ring(where, item)
        else:
            assert field_shape.shape is not None
            if type(item) is not field_shape.shape.record_type:
                raise InvalidRecordError(f"{where} is a {field_shape.shape.name}")
            validate_record(item, field_shape.shape)
    if kind in ("keys", "identities", "texts", "choices"):
        _distinct(name, items)
    if kind == "choices":
        order = [field_shape.values.index(item) for item in items]
        if order != sorted(order):
            raise InvalidRecordError(f"{name} lists its values in the order {field_shape.values}")
    if kind == "points":
        for index in range(1, len(items)):
            if items[index] == items[index - 1]:
                raise InvalidRecordError(f"{name}: points {index - 1} and {index} coincide")


# -------------------------------------------------------------------------------------------
# Reading a payload back


def read_record(payload: object, shape: RecordShape, where: str = "record") -> Any:
    """The instance a ``record_payload`` describes, validated. Nothing is filled in."""
    if shape.kind:
        if not isinstance(payload, dict) or set(payload) != {"kind", "version", "fields"}:
            raise InvalidRecordError(f"{where} is exactly kind, version and fields")
        if payload["kind"] != shape.kind:
            raise InvalidRecordError(f"{where} is a {shape.kind}, not {payload['kind']!r}")
        if type(payload["version"]) is not int or payload["version"] != shape.version:
            raise InvalidRecordError(f"{where}: {shape.kind} is version {shape.version}")
        fields = payload["fields"]
    else:
        fields = payload
    if not isinstance(fields, dict):
        raise InvalidRecordError(f"{where}: fields are an object")
    names = [field_shape.name for field_shape in shape.fields]
    unknown = sorted(set(fields) - set(names))
    missing = sorted(set(names) - set(fields))
    if unknown or missing:
        raise InvalidRecordError(f"{where}: unknown fields {unknown}, missing fields {missing}")
    values = {
        field_shape.name: _read_value(field_shape, fields[field_shape.name], where)
        for field_shape in shape.fields
    }
    return validate_record(shape.record_type(**values), shape)


def _list(where: str, raw: object) -> list[Any]:
    if not isinstance(raw, list):
        raise InvalidRecordError(f"{where} is a list")
    return raw


def _read_value(field_shape: FieldShape, raw: object, where: str) -> object:
    name = f"{where}.{field_shape.name}"
    kind = field_shape.kind
    if kind == "record":
        assert field_shape.shape is not None
        return read_record(raw, field_shape.shape, name)
    if kind == "records":
        assert field_shape.shape is not None
        return tuple(
            read_record(item, field_shape.shape, f"{name}[{index}]")
            for index, item in enumerate(_list(name, raw))
        )
    if kind == "ring" or kind == "points":
        return tuple(
            tuple(_list(f"{name}[{index}]", item)) for index, item in enumerate(_list(name, raw))
        )
    if kind == "rings":
        return tuple(
            tuple(
                tuple(_list(f"{name}[{index}][{corner}]", point))
                for corner, point in enumerate(_list(f"{name}[{index}]", item))
            )
            for index, item in enumerate(_list(name, raw))
        )
    if kind in _SEQUENCE_KINDS:
        return tuple(_list(name, raw))
    return raw


# -------------------------------------------------------------------------------------------
# A set of records


def describe_shapes(shapes: Iterable[RecordShape]) -> dict[str, object]:
    """The record table as plain data: every kind, and every nested shape it uses, once."""
    top: list[dict[str, object]] = []
    nested: dict[str, dict[str, object]] = {}

    def visit(shape: RecordShape) -> None:
        for field_shape in shape.fields:
            if field_shape.shape is not None and field_shape.shape.name not in nested:
                nested[field_shape.shape.name] = field_shape.shape.describe()
                visit(field_shape.shape)

    for shape in shapes:
        top.append(shape.describe())
        visit(shape)
    return {
        "records": sorted(top, key=lambda item: str(item["shape"])),
        "nested": [nested[name] for name in sorted(nested)],
    }


def _walk(value: object, shape: RecordShape) -> Iterable[tuple[FieldShape, object, object]]:
    """Every (field shape, value, record) in a record and in its nested records."""
    for field_shape in shape.fields:
        field_value = getattr(value, field_shape.name)
        yield field_shape, field_value, value
        if field_shape.kind == "record":
            assert field_shape.shape is not None
            yield from _walk(field_value, field_shape.shape)
        elif field_shape.kind == "records":
            assert field_shape.shape is not None
            for item in field_value:  # type: ignore[attr-defined]
                yield from _walk(item, field_shape.shape)


def index_records(
    records: Iterable[object], shapes: Mapping[type, RecordShape]
) -> dict[str, object]:
    """Every record with an identity, by identity. A repeated identity is refused."""
    index: dict[str, object] = {}
    for candidate in records:
        shape = shapes.get(type(candidate))
        if shape is None:
            raise InvalidRecordError(f"no shape for {type(candidate).__name__}")
        if shape.identity is None:
            continue
        own = getattr(candidate, shape.identity.field)
        if own in index:
            raise InvalidRecordError(f"identity {own} is stated by two records")
        index[own] = candidate
    return index


def check_references(
    records: Iterable[object],
    shapes: Mapping[type, RecordShape],
    index: Mapping[str, object],
) -> None:
    """Every identity a record names, at any depth, resolves to a record of an admitted kind."""
    for candidate in records:
        shape = shapes[type(candidate)]
        own_field = shape.identity.field if shape.identity is not None else ""
        for field_shape, value, holder in _walk(candidate, shape):
            if field_shape.kind not in ("identity", "identities"):
                continue
            if holder is candidate and field_shape.name == own_field:
                continue
            named = (value,) if field_shape.kind == "identity" else value
            for target in named:  # type: ignore[union-attr]
                referent = index.get(target)
                if referent is None:
                    raise InvalidRecordError(
                        f"{shape.name}.{field_shape.name} names {target}, which no record states"
                    )
                if (
                    field_shape.refers_to
                    and shapes[type(referent)].kind not in field_shape.refers_to
                ):
                    raise InvalidRecordError(
                        f"{shape.name}.{field_shape.name} names a "
                        f"{shapes[type(referent)].kind}, not one of {field_shape.refers_to}"
                    )


def check_identities(
    records: Iterable[object],
    shapes: Mapping[type, RecordShape],
    *,
    grammar_id: str,
    root_identity: str,
) -> None:
    """Every identity equals the rule's derivation from its owner and ordinal."""
    for candidate in records:
        shape = shapes[type(candidate)]
        rule = shape.identity
        if rule is None:
            continue
        owner = getattr(candidate, rule.owner_field) if rule.owner_field else root_identity
        expected = subject_identity(
            grammar_id=grammar_id,
            root_identity=root_identity,
            subject_kind=rule.subject_kind,
            owner_identity=owner,
            ordinal=rule.ordinal(candidate),
        )
        stated = getattr(candidate, rule.field)
        if stated != expected:
            raise InvalidRecordError(
                f"{shape.name} {stated} is not the identity its rule derives, {expected}"
            )


def check_vocabularies(
    records: Iterable[object],
    shapes: Mapping[type, RecordShape],
    vocabularies: Mapping[str, frozenset[str]],
) -> None:
    """Every key whose field names a vocabulary is a key of that vocabulary."""
    for candidate in records:
        shape = shapes[type(candidate)]
        for field_shape, value, _holder in _walk(candidate, shape):
            if not field_shape.vocabulary:
                continue
            if field_shape.vocabulary not in vocabularies:
                raise InvalidRecordError(
                    f"{shape.name}.{field_shape.name} resolves in {field_shape.vocabulary}, "
                    "which was not supplied"
                )
            known = vocabularies[field_shape.vocabulary]
            named = (value,) if field_shape.kind == "key" else value
            for item in named:  # type: ignore[union-attr]
                if item not in known:
                    raise InvalidRecordError(
                        f"{shape.name}.{field_shape.name} {item!r} is not a key of "
                        f"{field_shape.vocabulary}"
                    )
