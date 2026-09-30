"""Another decision role registry in use for one test, and roles made from the person's adapter.

The registry is one catalog the whole process reads (``decision_roles()``), as the engine table is.
A test that needs other roles writes a registry and a package of adapter modules, and puts them in
use for its duration: where the registry is read from is swapped, and the cached registry is
cleared on both sides of the swap, so nothing read under it outlives the test.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import exulanica.world.decision_roles as registry_module
from exulanica.world.decision_roles import REGISTRY_CATALOG, RoleRegistry, decision_roles

#: The production registry's newest version, whose person entry the roles below are made from.
PRODUCTION_REGISTRY: Path = registry_module.REGISTRY_DIRECTORY / f"{REGISTRY_CATALOG}.v1.json"
#: The person's adapter module, copied under another role key to make a role of the same kind.
PERSON_ADAPTER: Path = Path(registry_module.__file__).with_name("roles") / "person.py"


@contextmanager
def registry_in_use(directory: Path, adapters: str) -> Iterator[RoleRegistry]:
    """The registry in ``directory``, with adapters from the package ``adapters``, as the one
    every reader asks, until the block ends."""
    held = (registry_module.REGISTRY_DIRECTORY, registry_module.ADAPTER_PACKAGE)
    registry_module.REGISTRY_DIRECTORY = directory
    registry_module.ADAPTER_PACKAGE = adapters
    decision_roles.cache_clear()
    try:
        yield decision_roles()
    finally:
        registry_module.REGISTRY_DIRECTORY, registry_module.ADAPTER_PACKAGE = held
        decision_roles.cache_clear()


def person_entry() -> dict[str, Any]:
    """The production registry's person entry, as it states it."""
    document = json.loads(PRODUCTION_REGISTRY.read_text(encoding="utf-8"))
    (entry,) = [entry for entry in document["entries"] if entry["key"] == "society_decision"]
    return entry


def person_like(key: str, subject: str) -> dict[str, Any]:
    """The person's entry for another role deciding for people under the subject word
    ``subject``: its own key, adapter, profiles and prompt version, and the person's catalogs."""
    name = subject.replace("_", "-")
    return {
        **person_entry(),
        "key": key,
        "subject": subject,
        "adapter": key,
        "request_profile": f"exulanica.{name}-decision-request/v1",
        "receipt_profile": f"exulanica.{name}-decision/v1",
        "choice_profile": f"exulanica.{name}-model-choice/v1",
        "choice_subjects": "subjects",
        "context_profile": f"exulanica.{name}-decision-context/v1",
        "prompt_version": f"{name}-choice/v1",
    }


def write_registry(root: Path, entries: Sequence[Mapping[str, Any]]) -> tuple[Path, str]:
    """A registry of ``entries`` under ``root`` and a package on ``root`` holding each entry's
    adapter, the person's module serving that entry's key. The caller puts ``root`` on
    ``sys.path``. Returns the registry's directory and the package's name, which is new for every
    call so no module another test imported is read again."""
    package = f"g1_roles_{uuid.uuid4().hex}"
    (root / package).mkdir(parents=True)
    (root / package / "__init__.py").write_text('"""Adapters for one test."""\n', "utf-8")
    source = PERSON_ADAPTER.read_text(encoding="utf-8")
    for entry in entries:
        served = source.replace(
            'ROLE: Final = "society_decision"', f'ROLE: Final = "{entry["key"]}"'
        )
        assert served != source or entry["key"] == "society_decision"
        (root / package / f"{entry['adapter']}.py").write_text(served, encoding="utf-8")
    document = json.loads(PRODUCTION_REGISTRY.read_text(encoding="utf-8"))
    document["entries"] = [dict(entry) for entry in entries]
    directory = root / "registry"
    directory.mkdir()
    (directory / PRODUCTION_REGISTRY.name).write_text(json.dumps(document), encoding="utf-8")
    return directory, package
