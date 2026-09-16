"""Loopback-only development adapter for fitted human recipes. No account writes.

Expensive builds are content-addressed and reused. The application consumes ordinary
verified character assets; this adapter is not part of the production API.
"""

import argparse
import contextlib
import hashlib
import json
import math
import re
import shutil
import struct
import sys
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parametric_character.inputs import cache_key, preparation_identity, verify_inputs

ROOT = Path(__file__).resolve().parents[2]
FAMILY_ROOT = ROOT / "assets/characters/makehuman-parametric-v1"
FAMILY = json.loads((FAMILY_ROOT / "family.json").read_text())


def validate_recipe(value):
    if not isinstance(value, dict):
        raise ValueError("Expected body parameters")
    fields = FAMILY["controls"] + FAMILY["choices"]
    if set(value) != {c["key"] for c in fields}:
        raise ValueError("Body parameters do not match the selected family")
    result = {}
    for control in fields:
        v = value[control["key"]]
        if "options" in control:
            if v not in [o["value"] for o in control["options"]]:
                raise ValueError("Unsupported " + control["label"])
        elif (
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or not control["min"] <= v <= control["max"]
        ):
            raise ValueError("Out of range: " + control["label"])
        result[control["key"]] = v
    return result


class Builder:
    def __init__(self, blender, source):
        self.blender, self.source = blender, source
        self.lock = threading.Lock()
        # Keep transient output outside Vite's watched public tree. A completed build
        # must not reload the page and throw away the user's draft or applied selection.
        self.output = source / "runtime-assets"
        self.output.mkdir(parents=True, exist_ok=True)
        verify_inputs(source, blender, FAMILY_ROOT)

    def generate(self, value):
        recipe = validate_recipe(value)
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError("Another body is being fitted. Try again shortly.")
        try:
            # Verify again before a cache hit, and after a build before publishing bytes.
            # A changed extracted garment or tool must never reuse a previous result.
            if json.loads((FAMILY_ROOT / "family.json").read_text()) != FAMILY:
                raise ValueError("Body family changed; restart the preparation adapter")
            identity = preparation_identity(
                verify_inputs(self.source, self.blender, FAMILY_ROOT), FAMILY_ROOT
            )
            key = cache_key(identity, recipe)
            directory = self.source / "builds" / key
            result = directory / "result.json"
            if result.exists():
                saved = json.loads(result.read_text())
                asset = self.output / saved["file"]
                if (
                    asset.exists()
                    and hashlib.sha256(asset.read_bytes()).hexdigest()
                    == saved["descriptor"]["asset"]["contentSha256"]
                ):
                    return saved
            directory.mkdir(parents=True, exist_ok=True)
            config = dict(
                mpfb=str(self.source / "mpfb2"),
                cache=str(self.source / "mpfb-user"),
                recipe=recipe,
                family=FAMILY,
                assets=str(self.source / "system-assets"),
                animation=str(
                    (
                        FAMILY_ROOT
                        / json.loads((FAMILY_ROOT / "source-lock.json").read_text())[
                            "animationSource"
                        ]
                    ).resolve()
                ),
                output=str(directory / "human.glb"),
                metadata=str(directory / "metadata.json"),
            )
            config_path = directory / "config.json"
            config_path.write_text(json.dumps(config))
            with (directory / "build.log").open("w") as log:
                subprocess.run(
                    [
                        str(self.blender),
                        "--background",
                        "--factory-startup",
                        "--python-exit-code",
                        "1",
                        "--python",
                        str(Path(__file__).with_name("blender_build.py")),
                        "--",
                        str(config_path),
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=150,
                )
            if (
                preparation_identity(
                    verify_inputs(self.source, self.blender, FAMILY_ROOT), FAMILY_ROOT
                )
                != identity
            ):
                raise ValueError(
                    "Preparation inputs changed during the build; result was not published"
                )
            (directory / "input-receipt.json").write_text(json.dumps(identity, indent=2) + "\n")
            data = (directory / "human.glb").read_bytes()
            document = json.loads(data[20 : 20 + struct.unpack_from("<I", data, 12)[0]])
            metadata = json.loads((directory / "metadata.json").read_text())
            names = {a["name"] for a in document.get("animations", [])}
            if not {"HumanIdle", "HumanWalk", "HumanRun"} <= names or not document.get("skins"):
                raise ValueError("Generated human is missing required animation or skin data")
            digest = hashlib.sha256(data).hexdigest()
            file = "human-" + key + ".glb"
            descriptor = dict(
                asset=dict(
                    assetKey="preview-human-" + key,
                    mediaType="model/gltf-binary",
                    contentSha256=digest,
                    byteSize=len(data),
                ),
                rigId="makehuman-mixamo-unity/v1",
                joints=list(
                    dict.fromkeys(
                        document["nodes"][i]["name"] for s in document["skins"] for i in s["joints"]
                    )
                ),
                unitScale=metadata["scale"],
                standingHeight=metadata["height"],
                groundOffset=metadata["floor"],
                forwardYawDegrees=180,
                clips={
                    g: dict(
                        name="Human" + g.title(),
                        metresPerSecond=metadata["clips"][g]["metresPerSecond"] * metadata["scale"],
                    )
                    for g in ["idle", "walk", "run"]
                },
                rootMotion=dict(mode="in-place"),
                materialSlots={
                    m["name"]: dict(materials=[m["name"]]) for m in document["materials"]
                },
                morphParameters={},
                variantSlots={},
            )
            look = dict(
                lookId="human-" + key,
                label="Editable human",
                creator="MakeHuman Community · Quaternius motion",
                license="CC0",
                file=file,
                descriptor=descriptor,
                defaultColors=metadata["colors"],
                recipe=recipe,
                familyId=FAMILY["familyId"],
                generated=True,
                preparationReceipt=identity,
            )
            # Publish only complete, inspected output. The native loader checks these exact bytes again.
            shutil.copy2(directory / "human.glb", self.output / file)
            result.write_text(json.dumps(look, indent=2))
            return look
        finally:
            self.lock.release()


DEFAULT_ORIGINS = ("http://127.0.0.1:5192", "http://localhost:5192")


def loopback_origin(value):
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "http"
            and url.hostname in ("127.0.0.1", "localhost", "::1")
            and url.port is not None
            and url.port > 0
            and not url.username
            and not url.password
            and not url.path
            and not url.query
            and not url.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Expected an explicit HTTP loopback origin with a port")
    return value


def create_server(builder, port, allowed_origins=DEFAULT_ORIGINS):
    allowed_origins = frozenset(loopback_origin(origin) for origin in allowed_origins)
    if not allowed_origins:
        raise ValueError("At least one loopback origin must be allowed")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(data)

        def do_GET(self):
            if re.fullmatch(r"/assets/human-[a-f0-9]{64}\.glb", self.path):
                path = builder.output / self.path.rsplit("/", 1)[1]
                if not path.is_file():
                    return self.reply(404, {"error": "Character asset unavailable"})
                data = path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "model/gltf-binary")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.reply(200, FAMILY) if self.path == "/family" else self.reply(
                404, {"error": "Not found"}
            )

        def do_POST(self):
            if self.path != "/generate":
                return self.reply(404, {"error": "Not found"})
            if self.headers.get("Content-Type") != "application/json":
                return self.reply(415, {"error": "Expected JSON"})
            origin = self.headers.get("Origin", "")
            if origin and origin not in allowed_origins:
                return self.reply(
                    403, {"error": "This builder belongs to the local character preview"}
                )
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 8192:
                    raise ValueError("Invalid body request size")
                self.reply(200, builder.generate(json.loads(self.rfile.read(length))))
            except (ValueError, json.JSONDecodeError) as error:
                self.reply(400, {"error": str(error)})
            except BlockingIOError as error:
                self.reply(409, {"error": str(error)})
            except (subprocess.SubprocessError, OSError):
                self.reply(
                    503,
                    {
                        "error": "Body fitting failed. Your previous character is unchanged. Try less extreme proportions."
                    },
                )

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5196)
    parser.add_argument(
        "--allow-origin",
        action="append",
        type=loopback_origin,
        help="Repeat for each permitted local preview origin; replaces the 5192 defaults",
    )
    args = parser.parse_args()
    create_server(
        Builder(args.blender.resolve(), args.source.resolve()),
        args.port,
        args.allow_origin or DEFAULT_ORIGINS,
    ).serve_forever()
