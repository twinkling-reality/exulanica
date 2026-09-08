"""Serve two labelled generated images through an isolated real API and the actual app.

Run with PYTHONPATH=tests from the integrated checkout. Runtime tokens and content store
stay in a temporary directory.
The scratch schema is dropped when this process ends. No hosted model client is constructed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.parse
import uuid
from pathlib import Path

from exulanica.db.migrate import migrations, provision_workspace
from exulanica.db.roles import provision_runtime_role
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.ingest.person_detectors import NoRegionDetector
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from PIL import Image, ImageDraw

from conftest import photo_bytes
from pg_harness import migrated_schema, open_scratch_connection

ROOT = Path.cwd()
OUT = Path(__file__).resolve().parent / os.environ.get("MANUAL_REVIEW_RUN", ".")
OUT.mkdir(exist_ok=True)
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
os.environ["EXULANICA_TEST_DATABASE_URL"] = DATABASE
workspace, actor = uuid.uuid4(), uuid.uuid4()
with tempfile.TemporaryDirectory(prefix="manual-person-browser-") as temporary:
    runtime = Path(temporary)
    with migrated_schema() as (psycopg, owner):
        schema = owner.execute("select current_schema()").fetchone()[0]
        for migration in migrations():
            owner.execute(
                "insert into schema_migrations(version,checksum) values (%s,%s)",
                (migration.version, migration.checksum),
            )
        provision_runtime_role(owner)
        provision_runtime_role(owner, role="exulanica_ro", read_only=True)
        provision_workspace(owner, workspace)
        owner.commit()
        connection = open_scratch_connection(psycopg, schema)
        repository = IngestRepository(connection, workspace)
        store = LocalContentAddressedStore(runtime / "blobs")
        pipeline = PhotoIngestPipeline(repository, store, vision=None, detector=NoRegionDetector())
        captures = []
        for index in range(2):
            template = Image.open(
                io.BytesIO(
                    photo_bytes(size=(800, 400), when=f"2026:09:08 10:0{index}:00", gps=(0, 0))
                )
            )
            image = Image.new("RGB", (800, 400), (220, 230, 220 + index * 10))
            draw = ImageDraw.Draw(image)
            draw.text(
                (20, 20),
                f"GENERATED TEST IMAGE {index + 1} - NO REAL PERSON",
                fill="black",
                font_size=24,
            )
            draw.ellipse((220, 85, 280, 145), fill=(80, 90, 100))
            draw.rectangle((205, 150, 295, 285), fill=(90, 100, 110))
            draw.line((220, 285, 190, 365), fill="black", width=12)
            draw.line((280, 285, 310, 365), fill="black", width=12)
            target = OUT / f"generated-person-{index + 1}.jpg"
            image.save(target, exif=template.getexif(), quality=95)
            result = pipeline.ingest_intake(target.read_bytes(), filename=target.name)
            assert result.capture_id is not None, result.error
            authorization = authorize_synthetic_capture(
                repository,
                capture_id=result.capture_id,
                actor=actor,
                generator_manifest={"profile": "exulanica.manual-person-browser/v1",
                                    "notice": "GENERATED TEST IMAGE, NO REAL PERSON"},
                authorization_scope={"purpose": "isolated manual person browser acceptance"},
            )
            screening = record_synthetic_exemption(
                repository, authorization_id=authorization.authorization_id
            )
            result = pipeline.ingest_derivatives(
                result.capture_id, privacy_screening_id=screening.screening_id
            )
            assert result.error is None, result.error
            captures.append(
                (result.capture_id, hashlib.sha256(target.read_bytes()).hexdigest(), target.name)
            )
        run_scene_grouping(repository)
        groups = scene_group_rows(connection, workspace)
        assert groups, "generated inputs must produce a real scene group"
        compose_reference_sources(
            repository,
            region_id=str(groups[0].group_id),
            captures=captures,
            source_manifest_sha256=hashlib.sha256(b"generated manual person fixture").hexdigest(),
        )
        token = secrets.token_urlsafe(36)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("EXULANICA_", "ORIMERA_", "VITE_EXULANICA_"))
            and k not in {"NEBIUS_API_KEY", "PGOPTIONS", "PGDATABASE", "PGUSER"}
        }

        def url(role: str) -> str:
            return (
                DATABASE
                + "?options="
                + urllib.parse.quote(f"-csearch_path={schema},public -crole={role}", safe="")
            )

        env.update(
            EXULANICA_DATABASE_URL=url("exulanica_app"),
            EXULANICA_READONLY_DATABASE_URL=url("exulanica_ro"),
            EXULANICA_DATA_DIR=str(runtime),
            EXULANICA_DERIVATIVE_WORKER="0",
            EXULANICA_API_TOKENS=json.dumps(
                {token: {"workspace_id": str(workspace), "actor": str(actor)}}
            ),
            VITE_EXULANICA_TOKEN=token,
            VITE_EXULANICA_SOURCE_PRESENTATION="inspection",
            EXULANICA_API_URL="http://127.0.0.1:8137",
        )
        (OUT / "browser-fixture.json").write_text(
            json.dumps(
                {
                    "workspace_id": str(workspace),
                    "actor": str(actor),
                    "schema": schema,
                    "captures": [
                        {"capture_id": str(c), "sha256": h, "image": n} for c, h, n in captures
                    ],
                },
                indent=2,
            )
            + "\n"
        )
        processes = []
        try:
            for name, command in (
                (
                    "api",
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "exulanica.api.app:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8137",
                    ],
                ),
                (
                    "vite",
                    [
                        "pnpm",
                        "--dir",
                        "web",
                        "--filter",
                        "@exulanica/app",
                        "dev",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "5197",
                        "--strictPort",
                    ],
                ),
            ):
                log = (OUT / f"browser-{name}.log").open("w")
                processes.append(
                    subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
                )
            print("Generated fixture ready; actual app at http://127.0.0.1:5197", flush=True)
            while not (OUT / "browser-stop").exists():
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError("browser service stopped; inspect logs")
                # Persist exact stored outlines, no credentials and no floating point values.
                rows = connection.execute(
                    "select capture_id, region_key, silhouette, action, confirmed_by, subject_id "
                    "from person_region order by capture_id, sequence"
                ).fetchall()
                (OUT / "browser-stored-regions.json").write_text(
                    json.dumps(
                        [
                            {
                                k: v.hex()
                                if isinstance(v, bytes)
                                else str(v)
                                if isinstance(v, uuid.UUID)
                                else v
                                for k, v in row.items()
                            }
                            for row in rows
                        ],
                        indent=2,
                    )
                    + "\n"
                )
                time.sleep(1)
        finally:
            for process in processes:
                process.terminate()
            for process in processes:
                process.wait(timeout=20)
            connection.close()
