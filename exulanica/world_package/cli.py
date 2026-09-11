"""``exulanica-wmp``: project with PostgreSQL; verify, inspect, and diff without it."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from exulanica.world_package.authored import EXTENSION_KEY
from exulanica.world_package.diff import diff_packages
from exulanica.world_package.package import (
    PackageError,
    import_check_package,
    inspect_package,
    load_private_key,
    verify_package,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exulanica-wmp")
    commands = parser.add_subparsers(dest="command", required=True)

    project = commands.add_parser(
        "project", help="project and receipt one repeatable-read snapshot"
    )
    project.add_argument("--workspace", type=uuid.UUID, required=True)
    project.add_argument("--actor", type=uuid.UUID, required=True)
    project.add_argument("--output", type=Path, required=True)
    project.add_argument("--private-key", type=Path, required=True)
    project.add_argument("--world", default="atlas:default")
    project.add_argument("--parent-root")
    project.add_argument("--evaluation-report", action="append", default=[], type=Path)
    project.add_argument(
        "--extension",
        action="append",
        default=[],
        choices=[EXTENSION_KEY],
        help="add an optional, separately versioned extension; 1.0 payloads are unchanged",
    )

    decision = commands.add_parser(
        "training-consent", help="record an account-holder training attestation"
    )
    decision.add_argument("--workspace", type=uuid.UUID, required=True)
    decision.add_argument("--actor", type=uuid.UUID, required=True)
    decision.add_argument("--terms", type=Path, required=True)
    decision.add_argument(
        "--subject", required=True, help="person ID, or package-owner for package opt-in"
    )
    decision.add_argument("--decision", choices=("granted", "revoked", "withdrawn"), required=True)

    dataset = commands.add_parser(
        "training-export", help="explicitly export a consented dataset and receipt it"
    )
    dataset.add_argument("--workspace", type=uuid.UUID, required=True)
    dataset.add_argument("--actor", type=uuid.UUID, required=True)
    dataset.add_argument("--request", type=Path, required=True)
    dataset.add_argument("--output", type=Path, required=True)
    dataset.add_argument("--private-key", type=Path, required=True)
    dataset.add_argument(
        "--opt-in", action="store_true", help="explicitly enable this training export"
    )

    ledger = commands.add_parser(
        "training-ledger", help="read export terms, roots and subsequent revocations"
    )
    ledger.add_argument("--workspace", type=uuid.UUID, required=True)

    verify = commands.add_parser(
        "verify",
        help="verify bytes, inventory, policy, Merkle root, and signature; never loads a world",
    )
    verify.add_argument("package", type=Path)

    inspect = commands.add_parser("inspect", help="show a verified package summary")
    inspect.add_argument("package", type=Path)

    diff = commands.add_parser("diff", help="show a value-redacted semantic diff")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)

    import_check = commands.add_parser(
        "import-check", help="verify receiver compatibility without mutating a live world"
    )
    import_check.add_argument("package", type=Path)
    import_check.add_argument("--supported-style-profile", action="append", default=[])
    import_check.add_argument("--supported-interaction-capability", action="append", default=[])
    import_check.add_argument(
        "--loader-capability",
        action="append",
        default=[],
        help="one capability the receiving loader declares, for example "
        "wmp-extension:exulanica-wmp-ext-authored-world@1.0 or behaviour:motion.bounded-path@1",
    )

    keygen = commands.add_parser(
        "keygen-test",
        help="create an explicitly ephemeral Ed25519 test key; never provisions production trust",
    )
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "project":
            from exulanica.db import Database
            from exulanica.world_package.projector import project_world_package

            private_key = load_private_key(args.private_key)
            with Database.from_env().session(args.workspace) as connection:
                result = project_world_package(
                    connection,
                    workspace_id=args.workspace,
                    actor=args.actor,
                    output=args.output,
                    private_key=private_key,
                    world_id=args.world,
                    parent_merkle_root_sha256=args.parent_root,
                    evaluation_reports=args.evaluation_report,
                    extensions=args.extension,
                )
            _print(result.as_dict())
        elif args.command in {"training-consent", "training-export", "training-ledger"}:
            _training_command(args)
        elif args.command == "verify":
            _print(verify_package(args.package).as_dict())
        elif args.command == "inspect":
            _print(inspect_package(args.package))
        elif args.command == "diff":
            _print(diff_packages(args.before, args.after).as_dict())
        elif args.command == "import-check":
            _print(
                import_check_package(
                    args.package,
                    supported_style_profiles=frozenset(args.supported_style_profile),
                    supported_interaction_capabilities=frozenset(
                        args.supported_interaction_capability
                    ),
                    loader_capabilities=frozenset(args.loader_capability),
                )
            )
        elif args.command == "keygen-test":
            _write_ephemeral_test_key(args.private_key, args.public_key)
            _print(
                {
                    "private_key": str(args.private_key),
                    "public_key": str(args.public_key),
                    "warning": "ephemeral test key only; no production trust was provisioned",
                }
            )
        else:  # pragma: no cover - argparse enforces this branch away
            raise AssertionError(args.command)
    except (PackageError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


def _training_command(args: argparse.Namespace) -> None:
    from exulanica.consent.training import TrainingTerms
    from exulanica.db import Database
    from exulanica.ingest.repository import IngestRepository
    from exulanica.world_package.training_store import (
        export_training_dataset,
        record_training_decision,
        training_export_ledger,
    )

    if args.command == "training-export" and args.opt_in is not True:
        raise PackageError("training export is default off; --opt-in is required")
    with Database.from_env().session(args.workspace) as connection:
        repository = IngestRepository(connection, args.workspace)
        if args.command == "training-consent":
            terms = TrainingTerms.from_dict(json.loads(args.terms.read_bytes()))
            receipt = record_training_decision(
                repository,
                subject_id=args.subject,
                terms=terms,
                decision=args.decision,
                actor=args.actor,
            )
            _print(
                {
                    "receipt": receipt.as_dict(),
                    "receipt_sha256": receipt.digest,
                    "actor_basis": "account-holder attestation; no subject identity verification",
                }
            )
        elif args.command == "training-ledger":
            _print(training_export_ledger(repository))
        else:
            request = json.loads(args.request.read_bytes())
            if not isinstance(request, dict) or set(request) != {
                "terms",
                "materials",
                "attribution",
                "payment",
            }:
                raise PackageError(
                    "training request requires terms, materials, attribution and payment"
                )
            base = args.request.resolve().parent
            files = {}
            for material in request["materials"]:
                for asset in material["assets"]:
                    relative = Path(asset["path"])
                    if (
                        relative.is_absolute()
                        or ".." in relative.parts
                        or relative.parts[0] != "assets"
                    ):
                        raise PackageError("training assets must be relative paths under assets/")
                    source = base / relative
                    if not source.resolve().is_relative_to(base) or source.is_symlink():
                        raise PackageError("training asset escapes the request directory")
                    files[asset["path"]] = source.read_bytes()
            result = export_training_dataset(
                repository,
                output=args.output,
                files=files,
                materials=request["materials"],
                terms=TrainingTerms.from_dict(request["terms"]),
                actor=args.actor,
                private_key=load_private_key(args.private_key),
                owner_opt_in=args.opt_in,
                attribution=request["attribution"],
                payment=request["payment"],
            )
            _print(result)


def _write_ephemeral_test_key(private_path: Path, public_path: Path) -> None:
    if private_path.exists() or public_path.exists():
        raise PackageError("refusing to overwrite a signing key")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
