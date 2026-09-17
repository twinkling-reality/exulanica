"""Parameter migrations: how bindings written for one grammar version reach the next.

A grammar bump ships a pure migration from its predecessor, or it is not shippable: an edit log
recorded under version N is replayed under version N + 1 by running every binding through it. A
migration is a data object, ``<grammar_id>-migration.v<target>.json``, and this module holds it to
both parameter surfaces it joins.

**Total, by construction.** Every source level maps to a target level, keeping their order. Every
source parameter is carried, mapped or removed, exactly once, and every target parameter is
carried, mapped or introduced, exactly once. A carried integer is ``value * multiply + add`` with
``multiply >= 1``, so no migration can lose precision, and the whole source range must land inside
the target range. A mapped choice maps every source option to a target option. A removed
parameter and an introduced one each state a reason. A binding that sets a removed parameter is
not silently dropped: :meth:`ParameterMigration.migrate` returns it among ``dropped`` with the
removal's reason.

**Identity policy.** A migration also says what happens to subject identities, which carry
neither the seed nor the grammar version: ``preserved`` promises that the new version assigns every
``(kind, owner, ordinal)`` to the same subject as the old one did; ``rekeyed`` declares that it does
not, so an edit naming an old identity cannot be carried; ``introduced`` says the old version
derived no identities at all. Each comes with its reason.

A migration never looks at a seed and never draws. Chains compose with :func:`migrate_chain`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from exulanica.grammar.contract import GrammarKey, ParameterSurface
from exulanica.grammar.documents import read_json, split_versioned_name
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.parameters import CascadeBinding, ParameterSpec, ParameterValue
from exulanica.grammar.records import require_key, require_text

__all__ = [
    "IDENTITY_POLICIES",
    "CarriedParameter",
    "DroppedBinding",
    "IntroducedParameter",
    "MappedChoice",
    "MigrationResult",
    "ParameterMigration",
    "RemovedParameter",
    "migrate_chain",
]

IDENTITY_POLICIES: Final = ("preserved", "rekeyed", "introduced")
_MIGRATION_KEYS: Final = frozenset(
    {
        "schema_version",
        "grammar_id",
        "source_version",
        "target_version",
        "identity_policy",
        "identity_reason",
        "levels",
        "carried",
        "mapped",
        "removed",
        "introduced",
    }
)


def _object(where: str, value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidParameterError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _list(where: str, value: object) -> list[object]:
    if not isinstance(value, list):
        raise InvalidParameterError(f"{where} is a list")
    return value


@dataclass(frozen=True, slots=True)
class CarriedParameter:
    source: str
    target: str
    multiply: int
    add: int


@dataclass(frozen=True, slots=True)
class MappedChoice:
    source: str
    target: str
    options: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RemovedParameter:
    source: str
    reason: str


@dataclass(frozen=True, slots=True)
class IntroducedParameter:
    target: str
    reason: str


@dataclass(frozen=True, slots=True)
class DroppedBinding:
    level: str
    name: str
    value: ParameterValue
    reason: str


@dataclass(frozen=True, slots=True)
class MigrationResult:
    bindings: tuple[CascadeBinding, ...]
    dropped: tuple[DroppedBinding, ...]


@dataclass(frozen=True, slots=True)
class ParameterMigration:
    grammar_id: str
    source_version: int
    target_version: int
    identity_policy: str
    identity_reason: str
    levels: tuple[tuple[str, str], ...]
    carried: tuple[CarriedParameter, ...]
    mapped: tuple[MappedChoice, ...]
    removed: tuple[RemovedParameter, ...]
    introduced: tuple[IntroducedParameter, ...]

    def __post_init__(self) -> None:
        GrammarKey(self.grammar_id, self.source_version)
        GrammarKey(self.grammar_id, self.target_version)
        if self.target_version != self.source_version + 1:
            raise InvalidParameterError("a migration joins one version to the next")
        if self.identity_policy not in IDENTITY_POLICIES:
            raise InvalidParameterError(f"identity policy is one of {IDENTITY_POLICIES}")
        require_text("identity_reason", self.identity_reason)
        for entry in self.carried:
            require_key("carried source", entry.source)
            require_key("carried target", entry.target)
            if type(entry.multiply) is not int or entry.multiply < 1 or type(entry.add) is not int:
                raise InvalidParameterError(f"{entry.source}: multiply >= 1 and add are ints")
        for entry in self.mapped:
            require_key("mapped source", entry.source)
            require_key("mapped target", entry.target)
        for entry in self.removed:
            require_key("removed source", entry.source)
            require_text(f"{entry.source} reason", entry.reason)
        for entry in self.introduced:
            require_key("introduced target", entry.target)
            require_text(f"{entry.target} reason", entry.reason)

    @property
    def source_key(self) -> GrammarKey:
        return GrammarKey(self.grammar_id, self.source_version)

    @property
    def target_key(self) -> GrammarKey:
        return GrammarKey(self.grammar_id, self.target_version)

    @classmethod
    def read(cls, path: Path) -> ParameterMigration:
        stem, version = split_versioned_name(path)
        document = _object(path.name, read_json(path), set(_MIGRATION_KEYS))
        if type(document["schema_version"]) is not int or document["schema_version"] != 1:
            raise InvalidParameterError(f"{path.name}: schema_version is 1")
        if (f"{document['grammar_id']}-migration", document["target_version"]) != (stem, version):
            raise InvalidParameterError(f"{path.name} is not named for its grammar and target")
        levels = []
        for index, entry in enumerate(_list("levels", document["levels"])):
            pair = _object(f"levels[{index}]", entry, {"source", "target"})
            levels.append((pair["source"], pair["target"]))
        carried = tuple(
            CarriedParameter(
                **_object(f"carried[{index}]", entry, {"source", "target", "multiply", "add"})
            )  # type: ignore[arg-type]
            for index, entry in enumerate(_list("carried", document["carried"]))
        )
        mapped = []
        for index, entry in enumerate(_list("mapped", document["mapped"])):
            item = _object(f"mapped[{index}]", entry, {"source", "target", "options"})
            options = []
            for position, option in enumerate(_list(f"mapped[{index}].options", item["options"])):
                pair = _object(f"mapped[{index}].options[{position}]", option, {"source", "target"})
                options.append((pair["source"], pair["target"]))
            mapped.append(MappedChoice(item["source"], item["target"], tuple(options)))  # type: ignore[arg-type]
        removed = tuple(
            RemovedParameter(**_object(f"removed[{index}]", entry, {"source", "reason"}))  # type: ignore[arg-type]
            for index, entry in enumerate(_list("removed", document["removed"]))
        )
        introduced = tuple(
            IntroducedParameter(**_object(f"introduced[{index}]", entry, {"target", "reason"}))  # type: ignore[arg-type]
            for index, entry in enumerate(_list("introduced", document["introduced"]))
        )
        return cls(
            grammar_id=document["grammar_id"],  # type: ignore[arg-type]
            source_version=document["source_version"],  # type: ignore[arg-type]
            target_version=document["target_version"],  # type: ignore[arg-type]
            identity_policy=document["identity_policy"],  # type: ignore[arg-type]
            identity_reason=document["identity_reason"],  # type: ignore[arg-type]
            levels=tuple(levels),  # type: ignore[arg-type]
            carried=carried,
            mapped=tuple(mapped),
            removed=removed,
            introduced=introduced,
        )

    def check(self, source: ParameterSurface, target: ParameterSurface) -> None:
        """The migration is total over both surfaces and every value lands in range."""
        if (source.key, target.key) != (self.source_key, self.target_key):
            raise InvalidParameterError(
                f"this migration joins {self.source_key} to {self.target_key}, "
                f"not {source.key} to {target.key}"
            )
        level_map = dict(self.levels)
        if [pair[0] for pair in self.levels] != list(source.cascade.levels):
            raise InvalidParameterError("the level map lists every source level once, in order")
        mapped_levels = [level_map[level] for level in source.cascade.levels]
        for level in mapped_levels:
            if level not in target.cascade.levels:
                raise InvalidParameterError(f"{level!r} is not a target level")
        order = [target.cascade.levels.index(level) for level in mapped_levels]
        if order != sorted(set(order)):
            raise InvalidParameterError("the level map keeps the order and never merges levels")
        sources = (
            [entry.source for entry in self.carried]
            + [entry.source for entry in self.mapped]
            + [entry.source for entry in self.removed]
        )
        targets = (
            [entry.target for entry in self.carried]
            + [entry.target for entry in self.mapped]
            + [entry.target for entry in self.introduced]
        )
        if sorted(sources) != sorted(source.parameters.names()):
            raise InvalidParameterError(
                "every source parameter is carried, mapped or removed exactly once"
            )
        if sorted(targets) != sorted(target.parameters.names()):
            raise InvalidParameterError(
                "every target parameter is carried, mapped or introduced exactly once"
            )
        for entry in self.carried:
            before = source.parameters.get(entry.source)
            after = target.parameters.get(entry.target)
            if (before.kind, after.kind) != ("integer", "integer"):
                raise InvalidParameterError(f"{entry.source}: only an integer is carried")
            low = before.minimum * entry.multiply + entry.add
            high = before.maximum * entry.multiply + entry.add
            if low < after.minimum or high > after.maximum:
                raise InvalidParameterError(
                    f"{entry.source} lands in [{low}, {high}], outside {entry.target}'s range"
                )
            self._check_level(source, target, before, after, level_map)
        for entry in self.mapped:
            before = source.parameters.get(entry.source)
            after = target.parameters.get(entry.target)
            if (before.kind, after.kind) != ("choice", "choice"):
                raise InvalidParameterError(f"{entry.source}: only a choice is mapped")
            if sorted(pair[0] for pair in entry.options) != sorted(before.options):
                raise InvalidParameterError(f"{entry.source}: every source option is mapped once")
            for _old, new in entry.options:
                if new not in after.options:
                    raise InvalidParameterError(f"{entry.source}: {new!r} is not a target option")
            self._check_level(source, target, before, after, level_map)

    @staticmethod
    def _check_level(
        source: ParameterSurface,
        target: ParameterSurface,
        before: ParameterSpec,
        after: ParameterSpec,
        level_map: Mapping[str, str],
    ) -> None:
        finest = before.level or source.cascade.levels[-1]
        if not target.cascade.admits(after, level_map[finest]):
            raise InvalidParameterError(
                f"{before.name} may be set at {finest!r}, which maps to a level "
                f"{after.name} does not admit"
            )

    def migrate(
        self,
        source: ParameterSurface,
        target: ParameterSurface,
        bindings: Sequence[CascadeBinding],
    ) -> MigrationResult:
        """The bindings as the target version reads them, and every binding it could not carry."""
        self.check(source, target)
        level_map = dict(self.levels)
        carried = {entry.source: entry for entry in self.carried}
        mapped = {entry.source: entry for entry in self.mapped}
        removed = {entry.source: entry for entry in self.removed}
        seen: set[str] = set()
        migrated: list[CascadeBinding] = []
        dropped: list[DroppedBinding] = []
        for binding in bindings:
            if binding.level not in source.cascade.levels or binding.level in seen:
                raise InvalidParameterError(
                    f"{binding.level!r} is not one unrepeated level of {source.key}"
                )
            seen.add(binding.level)
            values: dict[str, ParameterValue] = {}
            for name, value in binding.values:
                spec = source.parameters.get(name)
                if not source.cascade.admits(spec, binding.level):
                    raise InvalidParameterError(f"{name} cannot be set at {binding.level!r}")
                spec.check(value)
                if name in carried:
                    entry = carried[name]
                    values[entry.target] = target.parameters.get(entry.target).check(
                        value * entry.multiply + entry.add  # type: ignore[operator]
                    )
                elif name in mapped:
                    choice = mapped[name]
                    values[choice.target] = dict(choice.options)[value]  # type: ignore[index]
                else:
                    dropped.append(DroppedBinding(binding.level, name, value, removed[name].reason))
            migrated.append(CascadeBinding.of(level_map[binding.level], values))
        return MigrationResult(tuple(migrated), tuple(dropped))


def migrate_chain(
    migrations: Sequence[ParameterMigration],
    surfaces: Mapping[int, ParameterSurface],
    bindings: Sequence[CascadeBinding],
    *,
    from_version: int,
    to_version: int,
) -> MigrationResult:
    """Every migration from ``from_version`` to ``to_version``, in order, dropped bindings kept."""
    by_source = {migration.source_version: migration for migration in migrations}
    current = tuple(bindings)
    dropped: list[DroppedBinding] = []
    for version in range(from_version, to_version):
        migration = by_source.get(version)
        if migration is None:
            raise InvalidParameterError(f"no migration from version {version}")
        result = migration.migrate(surfaces[version], surfaces[version + 1], current)
        current = result.bindings
        dropped.extend(result.dropped)
    return MigrationResult(current, tuple(dropped))
