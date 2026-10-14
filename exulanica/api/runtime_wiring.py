"""How a running instance wires the runtimes it serves its society, material and character reads
from: the society runtime with any host registrations of saved worlds, the material recipes over its
stores, and the character appearance runtime with its queued body preparations.

:func:`exulanica.api.services.build_services` calls each once at startup and names them again, so a
caller that reads one from there keeps working.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

from exulanica.api.instance_settings import SOCIETY_AUTHORED_WORLDS_ENV
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.env import env_get
from exulanica.store.base import ContentAddressedStore
from exulanica.store.configured import ContentStores
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.material_recipes import MaterialRuntime
from exulanica.world.society_composition import REVIEWED_REACH_MM, reviewed_affordance_registry
from exulanica.world.texture_assets import load_material_catalog

if TYPE_CHECKING:
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

#: The registration file's own profile, so a file written for a later shape is refused here
#: rather than half-read.
AUTHORED_WORLDS_PROFILE: Final = "exulanica.society-authored-worlds/v1"


def _society_runtime(store: ContentAddressedStore, environ: Mapping[str, str]) -> SocietyRuntime:
    """The society runtime every instance serves, inert until somebody asks for inhabitants.

    It composes a saved world over the ground the world's own snapshot declares when its owner
    brings inhabitants in, and it creates, starts and schedules nothing by itself. District
    bindings are never inferred.

    ``EXULANICA_SOCIETY_AUTHORED_WORLDS`` optionally names a JSON file of host registrations,
    each naming a workspace, a saved world, its authored version, that version's structural
    snapshot, the authored region of that snapshot and the workspace place identity the society
    row binds, and optionally the reviewed reach. Nothing in it is inferred: a file that names a
    world whose snapshot is not an authored starter, or whose region is not that snapshot's own,
    fails at the first request with the reason rather than composing something else. A file that
    is present and malformed stops startup, because an instance that silently ignores a
    registration it was given is the failure this refuses to become.
    """
    path = env_get("SOCIETY_AUTHORED_WORLDS", environ)
    reach_mm = REVIEWED_REACH_MM
    bindings: list[AuthoredWorldSocietyBinding] = []
    if path:
        document = json.loads(Path(path).read_bytes())
        if not isinstance(document, dict) or document.get("profile") != AUTHORED_WORLDS_PROFILE:
            raise ValueError(
                f"{SOCIETY_AUTHORED_WORLDS_ENV} must name a {AUTHORED_WORLDS_PROFILE} file"
            )
        reach_mm = document.get("reach_mm", REVIEWED_REACH_MM)
        bindings = [AuthoredWorldSocietyBinding.model_validate(row) for row in document["worlds"]]
    return SocietyRuntime(
        store=store,
        authored_bindings=bindings,
        reviewed_affordances=reviewed_affordance_registry(reach_mm),
    )


def _material_runtime(stores: ContentStores, environ: Mapping[str, str]) -> MaterialRuntime | None:
    """The published makers and each workspace's bake namespace, when the catalog is here.

    ``EXULANICA_TEXTURE_DIRECTORY`` names the catalog in an image; a checkout finds its own. The
    catalog is verified against its pins on the way in, so a directory that is present but not
    the reviewed one raises :class:`TextureCatalogError` and stops startup, rather than being
    reported as absent. Only a missing catalog is an absence, and ``warnings`` says so.
    """
    directory = env_get("TEXTURE_DIRECTORY", environ)
    try:
        catalog = load_material_catalog(Path(directory)) if directory else load_material_catalog()
    except FileNotFoundError:
        return None
    return MaterialRuntime(catalog=catalog, stores=stores.materials)


def _character_appearance_runtime(
    store: ContentAddressedStore,
    environ: Mapping[str, str],
    workspace_stores: WorkspaceStores | None = None,
) -> CharacterAppearanceRuntime | None:
    """Saved looks over the character catalogs this host publishes (migration 0131).

    A family is served while a publication that derives it is not withdrawn, and a saved look is
    drawn from the newest served publication deriving exactly its family. Publishing is host
    administration, not startup: ``exulanica-character-catalog publish`` (or
    ``scripts/prepare_character_people.py --import --apply``) imports the containers and records the
    publication with the owner connection, so this instance reads the catalogs from the database
    on every request and a publication or withdrawal takes effect without a restart. With nothing
    published, the families read is empty and saving a look answers 424.

    Bodies a parametric family does not publish are prepared in the workspace's own preparation
    queue, in the workspace asset namespaces (``workspace_stores``; without them no body is
    prepared here). ``EXULANICA_CHARACTER_PREPARER_BLENDER`` and
    ``EXULANICA_CHARACTER_PREPARER_SOURCE`` name the pinned preparation inputs; without them, or
    when they do not verify, a request for a body answers 503 and nothing is queued.
    """
    from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime
    from exulanica.world.character_body_preparations import QueuedCharacterPreparations
    from exulanica.world.character_catalogs import CatalogRegistry
    from exulanica.world.character_preparation import CharacterBodyPreparer, environment_host
    from exulanica.world.workspace_preparations import WorkspacePreparationRepository

    return CharacterAppearanceRuntime(
        families=(),
        authorize_family=lambda _connection, _session, _family: False,
        store=store,
        catalogs=CatalogRegistry(),
        preparations=None
        if workspace_stores is None
        else lambda connection, session: QueuedCharacterPreparations(
            WorkspacePreparationRepository(
                connection, session.workspace_id, session.actor, stores=workspace_stores
            )
        ),
        preparer=None
        if workspace_stores is None
        else CharacterBodyPreparer(hosts=lambda family_id: environment_host(family_id, environ)),
    )
