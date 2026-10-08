"""The operator's command for a workspace's own looks: admit one a bridge's mapping names, withdraw
one, list them.

    python -m exulanica.api.thing_store_command admit-look --workspace UUID --actor UUID \\
        --document LOOK.json --container LOOK.glb --mapping MAPPING.json [--apply]
    python -m exulanica.api.thing_store_command withdraw-look --workspace UUID --actor UUID \\
        --look KEY --version N --reason TEXT [--apply]
    python -m exulanica.api.thing_store_command list --workspace UUID

A traveller who crosses in from an outside game arrives looking like itself only when the
workspace holds that look. A deployment builds the look from its own copy of the game's figure
(the bridge's look builder writes a look document and its container, never committed), and this
command admits the pair into one workspace's store (:meth:`ThingStore.admit_look`) only as the
bridge's mapping names it:

- the mapping is a file whose digest a bridge the deployment declares pins
  (``EXULANICA_DOOR_BRIDGES``, :func:`exulanica.door.bridges.load_bridge_directory`), read by the
  door's own check (:func:`exulanica.door.mapping.check_mapping`);
- one of the mapping's looks names the look document's digest, and that entry's source digest is
  among the look's ingredients, its SPDX identifier is the look's, and its share-alike mark is the
  look's. A document relabelled under another licence has another digest, and no mapping names it.

It is run once for each workspace that grants such travellers. It sits with the HTTP surface
because only that layer may read the door's mapping and the world's store together.

Without ``--apply`` each command makes every check that needs no database and writes nothing:
``admit-look`` the store's own (:func:`exulanica.world.thing_store.read_admission`) and the
mapping's, a look drawn on a plan the workspace drafted being read only with ``--apply``;
``withdraw-look`` its reason's, one plain line.

The database is ``EXULANICA_DATABASE_URL``; the container goes to the workspace's ``looks``
namespace of the store this deployment's API serves from.
"""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import CanonicalisationError, sha256_of_canonical
from exulanica.door.bridges import BridgeDirectory, BridgeSettingRefused, load_bridge_directory
from exulanica.door.mapping import MappingRefused, check_mapping, check_plain
from exulanica.things.looks import Look
from exulanica.world.thing_store import (
    ThingStore,
    ThingStoreRefused,
    read_admission,
    read_withdrawal_reason,
)

__all__ = ["MappingNotAdmitted", "admitted_mapping", "main", "mapping_admits"]


class MappingNotAdmitted(ValueError):
    """A mapping file no bridge the deployment declares pins by digest."""

    code: Final = "mapping_not_admitted"


def admitted_mapping(raw: bytes, directory: BridgeDirectory) -> dict[str, Any]:
    """The mapping file ``raw`` as the deployment admits it: one JSON object whose canonical digest
    a declared bridge pins, read by the door's mapping check. Or :class:`MappingRefused` for a
    document that is not a mapping, and :class:`MappingNotAdmitted` for one no bridge pins."""
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MappingRefused(f"the mapping is not JSON: {exc}") from exc
    check_plain(document)
    try:
        digest = sha256_of_canonical(document).hex()
    except CanonicalisationError as exc:
        raise MappingRefused(str(exc)) from exc
    if not any(digest in bridge.mapping_sha256 for bridge in directory.bridges.values()):
        raise MappingNotAdmitted(
            f"no bridge this deployment declares pins the mapping with digest {digest}"
        )
    return check_mapping(document)


def _named_digest(named: str | Mapping[str, Any]) -> str:
    """The digest a mapping's look entry names its look by: ``sha256:<digest>`` in a
    ``bridge-mapping/v1`` mapping, the library's reference ``{look, version, sha256}`` in a
    ``bridge-mapping/v2`` one."""
    return named.removeprefix("sha256:") if isinstance(named, str) else str(named["sha256"])


def mapping_admits(mapping: Mapping[str, Any]) -> Callable[[Look], None]:
    """The intake's own check for one admitted mapping: an imported look that one of the mapping's
    looks names, by its digest or by its whole reference (key, version and digest), whose source
    digest is among the look's ingredients, under the SPDX identifier and share-alike mark the
    entry states; or :class:`ThingStoreRefused` (``look_not_admitted``)."""
    entries = {
        _named_digest(entry["look"]): entry
        for visitor in mapping["visitors"]
        for entry in visitor["looks"]
    }

    def admit(look: Look) -> None:
        entry = entries.get(look.sha256)
        if entry is None:
            raise ThingStoreRefused(
                "look_not_admitted", "the admitted mapping names no look with this digest"
            )
        named = entry["look"]
        origin = look.document["origin"]
        stated = entry["licence"]
        if (
            (not isinstance(named, str) and dict(named) != look.reference())
            or origin["class"] != "imported"
            or entry.get("source_sha256") not in origin["lineage"]["ingredients"]
            or stated["spdx"] != origin["licence"]["spdx"]
            or stated.get("share_alike", False) != origin["licence"]["share_alike"]
        ):
            raise ThingStoreRefused(
                "look_not_admitted",
                "the look's origin is not the one the admitted mapping states for it",
            )

    return admit


def _workspace(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def _refused(exc: MappingRefused | MappingNotAdmitted | ThingStoreRefused) -> int:
    if isinstance(exc, ThingStoreRefused):
        print(f"refused: {exc}")
    else:
        print(f"refused: {exc.code}: {exc}")
    return 1


def _connect(parser: argparse.ArgumentParser) -> psycopg.Connection:
    from exulanica.env import env_get

    url = env_get("DATABASE_URL")
    if not url:
        parser.error("EXULANICA_DATABASE_URL is required")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def _admit_look(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    try:
        directory = load_bridge_directory()
    except BridgeSettingRefused as exc:
        parser.error(str(exc))
    container = args.container.read_bytes()
    try:
        try:
            document = json.loads(args.document.read_bytes())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ThingStoreRefused(
                "look_refused", f"the look document is not JSON: {exc}"
            ) from exc
        admit = mapping_admits(admitted_mapping(args.mapping.read_bytes(), directory))
        if not args.apply:
            look = read_admission(document, container).look
            admit(look)
            print(f"would admit {look.look} v{look.version} {look.sha256} into {args.workspace}")
            return 0
        from exulanica.db.session import set_workspace
        from exulanica.store.configured import content_stores

        looks = content_stores(data_dir=args.data_dir).looks.for_workspace(args.workspace)
        with _connect(parser) as connection:
            set_workspace(connection, args.workspace)
            kept = ThingStore(connection, args.workspace, looks).admit_look(
                document, container, created_by=args.actor, admit=admit
            )
    except (MappingRefused, MappingNotAdmitted, ThingStoreRefused) as exc:
        return _refused(exc)
    print(
        f"admitted {kept.look.look} v{kept.look.version} {kept.look.sha256} into "
        f"{args.workspace}: container {kept.container_sha256} ({kept.container_profile})"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m exulanica.api.thing_store_command", description=__doc__
    )
    commands = parser.add_subparsers(dest="command", required=True)
    admit = commands.add_parser("admit-look", help="admit a look a bridge's mapping names")
    admit.add_argument("--workspace", type=_workspace, required=True)
    admit.add_argument("--actor", type=_workspace, required=True)
    admit.add_argument("--document", type=Path, required=True)
    admit.add_argument("--container", type=Path, required=True)
    admit.add_argument("--mapping", type=Path, required=True)
    admit.add_argument("--data-dir", type=Path)
    admit.add_argument("--apply", action="store_true", help="write; otherwise only check")
    withdraw = commands.add_parser("withdraw-look", help="withdraw one of a workspace's looks")
    withdraw.add_argument("--workspace", type=_workspace, required=True)
    withdraw.add_argument("--actor", type=_workspace, required=True)
    withdraw.add_argument("--look", required=True)
    withdraw.add_argument("--version", type=int, required=True)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--apply", action="store_true")
    listing = commands.add_parser("list", help="the looks a workspace holds")
    listing.add_argument("--workspace", type=_workspace, required=True)
    args = parser.parse_args(argv)

    if args.command == "admit-look":
        return _admit_look(args, parser)
    if args.command == "withdraw-look":
        try:
            read_withdrawal_reason(args.reason)
        except ThingStoreRefused as exc:
            return _refused(exc)
        if not args.apply:
            print(
                f"would withdraw {args.look} v{args.version} from {args.workspace} ({args.reason})"
            )
            return 0

    from exulanica.db.session import set_workspace

    with _connect(parser) as connection:
        set_workspace(connection, args.workspace)
        if args.command == "list":
            for row in connection.execute(
                "select l.key, l.version, l.sha256, l.origin_class, l.spdx, l.container_profile, "
                "w.reason from look_version l left join look_withdrawal w on "
                "w.workspace_id=l.workspace_id and w.key=l.key and w.version=l.version "
                "where l.workspace_id=%s order by l.key, l.version",
                (args.workspace,),
            ).fetchall():
                state = f"withdrawn ({row['reason']})" if row["reason"] else "held"
                print(
                    f"{row['key']} v{row['version']} {row['sha256']} {row['origin_class']} "
                    f"{row['spdx']} {row['container_profile']} {state}"
                )
            return 0
        try:
            ThingStore(connection, args.workspace, None).withdraw_look(
                args.look, args.version, args.reason, withdrawn_by=args.actor
            )
        except ThingStoreRefused as exc:
            return _refused(exc)
    print(f"withdrew {args.look} v{args.version} from {args.workspace}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
