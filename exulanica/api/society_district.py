"""Read the exact host-registered district under the existing society source authority."""

from __future__ import annotations

import uuid
from typing import Any, Literal

import psycopg
from pydantic import BaseModel, ConfigDict

from exulanica.api.society_runtime import SocietyRuntime
from exulanica.selection.validation import Session
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput


class SocietyDistrictView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["exulanica.society-district-view/v1"] = "exulanica.society-district-view/v1"
    registration: dict[str, Any]
    place_id: uuid.UUID
    base_artifact_sha256: str
    interpretation_artifact_sha256: str
    interpretation_document_sha256: str
    current_dependencies: dict[str, Literal["available"]]
    base_json: str
    interpretation_json: str


def society_district_view(
    runtime: SocietyRuntime,
    connection: psycopg.Connection,
    session: Session,
    version_id: uuid.UUID,
    *,
    world_id: str,
) -> SocietyDistrictView:
    """One locked read, using the same frame/version/source checks as society decisions.

    ``world_id`` is the world the caller named. A version of another world is refused exactly as
    a version with no registered district is, so the answer says nothing about other worlds.

    Strings preserve exact UTF-8 blob bytes, including whitespace and terminal newlines. The
    client verifies their artifact hashes before parsing; a parsed/re-serialized model would not
    preserve that property. This grants no rights and fabricates no reconstruction capability.
    """
    try:
        binding = runtime._binding(session, version_id)
    except UnavailableSocietyInput as exc:
        raise UnknownWorldResource("no registered society district for this version") from exc
    if binding.world_id != world_id:
        raise UnknownWorldResource("no registered society district for this version")
    with connection.transaction():
        connection.execute("set transaction read only")
        runtime._lock(connection, session)
        try:
            version = runtime._version(connection, session, binding)
        except UnavailableSocietyInput as exc:
            if isinstance(exc.__cause__, UnknownWorldResource):
                raise UnknownWorldResource("no such alternate version") from exc
            raise
        if version.source_invalidated:
            raise UnavailableSocietyInput("authored source invalidated")
        # _district checks current operation rights, exact source receipts and all pinned
        # geometry/frame relationships. _blob verifies the second immutable read against its pin.
        _, base_bytes, _ = runtime._district(connection, session, binding)
        interpretation_bytes = runtime._blob(binding.interpretation_artifact_sha256)
        try:
            base_json = base_bytes.decode("utf-8")
            interpretation_json = interpretation_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnavailableSocietyInput("district JSON is not UTF-8") from exc
        return SocietyDistrictView(
            registration=binding.registration(),
            place_id=binding.place_id,
            base_artifact_sha256=binding.base_artifact_sha256,
            interpretation_artifact_sha256=binding.interpretation_artifact_sha256,
            interpretation_document_sha256=binding.interpretation_document_sha256,
            current_dependencies={source.source_sha256: "available" for source in binding.sources},
            base_json=base_json,
            interpretation_json=interpretation_json,
        )
