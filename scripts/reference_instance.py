"""Run the retained local Atlas reference in the explicitly permitted test database."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import uuid
from pathlib import Path

from exulanica.db import Database, provision_workspace

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".exulanica/reference-baseline/runtime"
CONFIG = STATE / "access.json"
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "init",
            "api",
            "web",
            "sources-worker",
            "depth-worker",
            "workflow",
            "compose",
            "queue",
        ),
    )
    parser.add_argument("--scene", default="bowl", help="Stable local workspace label")
    parser.add_argument("--port", type=int, default=5180, help="Atlas dev-server port")
    args, remaining = parser.parse_known_args()
    if re.fullmatch(r"[a-z][a-z0-9-]{0,63}", args.scene) is None:
        parser.error("scene must be a lowercase path-safe label")
    if args.command == "init":
        STATE.mkdir(parents=True, exist_ok=True)
        if not CONFIG.exists():
            config = {"actor": str(uuid.uuid4()), "scenes": {}}
            with CONFIG.open("x") as stream:
                os.chmod(CONFIG, 0o600)
                json.dump(config, stream, indent=2)
        config = json.loads(CONFIG.read_bytes())
        if args.scene not in config["scenes"]:
            config["scenes"][args.scene] = {
                "workspace_id": str(uuid.uuid4()),
                "token": secrets.token_urlsafe(36),
            }
            CONFIG.write_text(json.dumps(config, indent=2) + "\n")
        database = Database(DATABASE)
        for scene in config["scenes"].values():
            workspace = uuid.UUID(scene["workspace_id"])
            with database.session(workspace) as connection:
                provision_workspace(connection, workspace)
        print(
            f"Retained local workspace identities configured in {CONFIG}; credentials not printed."
        )
        return 0
    config = json.loads(CONFIG.read_bytes())
    scene = config["scenes"][args.scene]
    # Never inherit a personal deployment URL, model credential or database-creation opt-in.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("EXULANICA_", "ORIMERA_", "VITE_EXULANICA_"))
        and key not in {"NEBIUS_API_KEY", "PGOPTIONS", "PGDATABASE", "PGUSER"}
    }
    env.update(
        {
            "EXULANICA_DATABASE_URL": DATABASE,
            "EXULANICA_READONLY_DATABASE_URL": DATABASE + "?options=-crole%3Dexulanica_ro",
            "EXULANICA_DATA_DIR": str(STATE),
            "EXULANICA_DERIVATIVE_WORKER": "0",
            "EXULANICA_WORKSPACE_IDS": scene["workspace_id"],
            "EXULANICA_REFERENCE_TOKEN": scene["token"],
            "PGOPTIONS": "-c role=exulanica_app",
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    entry["token"]: {
                        "workspace_id": entry["workspace_id"],
                        "actor": config["actor"],
                    }
                    for entry in config["scenes"].values()
                }
            ),
        }
    )
    if args.command == "api":
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "exulanica.api.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
    elif args.command == "web":
        env["VITE_EXULANICA_TOKEN"] = scene["token"]
        port = str(args.port)
        cmd = [
            "pnpm",
            "--dir",
            str(ROOT / "web"),
            "--filter",
            "@exulanica/app",
            "dev",
            "--host",
            "127.0.0.1",
            "--port",
            port,
            "--strictPort",
        ]
    elif args.command in {"sources-worker", "depth-worker"}:
        env["EXULANICA_DEPTH_MODEL"] = "moge" if args.command == "depth-worker" else "unavailable"
        if args.command == "depth-worker":
            env["EXULANICA_DEPTH_DEVICE"] = "mps"
        cmd = [sys.executable, "-m", "exulanica.ingest.worker_command", "--once"]
    elif args.command == "queue":
        cmd = [
            sys.executable,
            str(ROOT / "scripts/queue_reference_reconstruction.py"),
            "--workspace",
            scene["workspace_id"],
            "--actor",
            config["actor"],
            *remaining,
        ]
    elif args.command == "compose":
        cmd = [
            sys.executable,
            str(ROOT / "scripts/compose_reference_sources.py"),
            "--workspace",
            scene["workspace_id"],
            "--scene",
            args.scene,
            *remaining,
        ]
    else:
        cmd = [sys.executable, str(ROOT / "scripts/reference_scene.py"), *remaining]
    return subprocess.call(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
