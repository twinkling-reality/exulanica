"""Every documentation path this repository names must resolve, and records must never be stranded.

Three separate rules live here and they exist for different reasons.

**Rule 1, ordinary link rot.** Nothing checked a markdown link or a ``docs/...`` string in a comment
until now, and the cost of that was already paid: ``adr/0008-generated-geometry.md`` points at
``license-matrix.md:441``, which lands on a blank line, and nobody noticed. MEASURED 2026-09-09
across the tree: 1,319 references to 740 distinct documentation paths, ten of which did not resolve.

**Rule 2, and this is the one worth the file.** ``docs/evaluation/`` holds digest-bound records that
cannot be edited: correcting a path inside one would change its ``record_sha256``, which every
record naming it as a predecessor binds in turn, cascading through the chain. So a record that names
``docs/demo-runbook.md`` has pinned that path **permanently**. Nineteen root documents, fourteen
ADRs and one patch are pinned this way today. ``tests/test_retained_evaluation_records.py`` resolves
the ``captures`` and ``predecessor_record`` paths, which are the ones carrying digests; it does not
look at paths named in prose, and those are exactly as unmovable. Without this rule, a future
reorganisation strands them silently and the strand cannot be repaired afterwards.

**Rule 3, relative links between documents.** The same rot as rule 1, in the form the documentation
actually uses most.

WHAT IS ALLOWED TO DANGLE, and why an allowlist rather than a filter. Every known-unresolved
reference is named below with its reason, so a new one fails loudly. Two of them are more useful
than a clean list would be: a brief that names a deliverable which was never produced is evidence
that commissioned work did not close out, and hiding that behind a clever exemption for briefs would
throw away the signal. They are recorded in ``docs/engineering-log.md`` instead.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_TEMPLATE = "template text in the document's own instructions"

#: A reference this tree cannot satisfy today, and why it is not a defect to be fixed here.
ALLOWED_DANGLING: dict[str, str] = {
    "docs/evaluation/NEW-asset-read-currency.json": _TEMPLATE,
    "docs/evaluation/NEW-personal-admission-flow.json": _TEMPLATE,
    "docs/evaluation/NEW-screening-currency.json": _TEMPLATE,
    "docs/evaluation/PRIOR.json": "a placeholder in the recorder's usage string, not a real path",
    "docs/recovery-drill-2026-09-08.md": (
        "docs/briefs/2026-09-08-isolated-recovery-drill.md names this as a deliverable and it was "
        "never produced. Kept visible on purpose: the brief is a plan and the gap is the finding."
    ),
    "docs/retained-activation-2026-09-08.md": (
        "docs/briefs/2026-09-08-retained-activation.md names it as a deliverable and it was "
        "never produced. Same reason as above."
    ),
    "docs/evaluation/2026-09-08-isolated-recovery-drill.json": (
        "the record its brief commissioned, never written; the work did not close out"
    ),
    "docs/evaluation/2026-09-08-retained-activation.json": (
        "the record its brief commissioned, never written; the work did not close out"
    ),
    "docs/generated-tier-disclosure.md": (
        "docs/records/2026-09-08-integration.md describes a branch that created this file; it "
        "is not in this tree, so either the branch did not land or it was renamed on the way in"
    ),
}

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", "dist"}
_TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".json", ".mjs", ".js", ".ts", ".tsx", ".cjs", ".yml", ".yaml",
}

#: A path inside a URL belongs to somebody else's repository. MEASURED: without this, the external
#: `deep-person-reid` model zoo link in evaluation-methodology.md reads as a local dangling path.
_URL = re.compile(r"https?://\S+")
_DOC_PATH = re.compile(r"docs/[A-Za-z0-9][A-Za-z0-9/._-]*\.(?:md|json|patch|txt|png|py)")
_MD_LINK = re.compile(r"\]\(([A-Za-z0-9][A-Za-z0-9/._-]*\.md)(?:#[^)]*)?\)")


def _text_files() -> list[Path]:
    """Every tracked text file. Tracked, not present: the gitignored working areas hold private
    notes that name documents which never existed in this tree, and a gate that failed on a
    scratch directory nobody committed would be measuring the author's desk, not the repository.
    MEASURED 2026-09-09: `.orimera/` named three such paths and failed the merged suite."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode()
    found = []
    for relative in filter(None, listed.split("\0")):
        path = ROOT / relative
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        # The artifact tree is large and holds captured logs rather than references.
        if "docs/evaluation/artifacts" in path.as_posix():
            continue
        if path.is_file() and path.suffix in _TEXT_SUFFIXES:
            found.append(path)
    return found


def _referenced_paths(text: str) -> set[str]:
    return set(_DOC_PATH.findall(_URL.sub(" ", text)))


def test_every_documentation_path_named_anywhere_in_the_repository_resolves():
    """Rule 1. A pointer nobody can follow is worse than no pointer, because it looks like one."""
    broken: dict[str, list[str]] = {}
    for path in _text_files():
        rel = path.relative_to(ROOT).as_posix()
        for ref in _referenced_paths(path.read_text(encoding="utf-8", errors="replace")):
            if ref in ALLOWED_DANGLING or (ROOT / ref).exists():
                continue
            broken.setdefault(ref, []).append(rel)
    assert not broken, "documentation paths that do not resolve:\n" + "\n".join(
        f"  {ref}  named by {', '.join(sorted(set(who))[:3])}"
        for ref, who in sorted(broken.items())
    )


def _relative_link_origin(path: Path, brief_origins: dict[bytes, Path]) -> Path:
    """An exact frozen prompt retains the source document's relative-link context.

    Only artifact brief.md copies qualify, and complete byte equality verifies their
    origin. A changed copy or an ordinary document must resolve from its own directory.
    """
    if path.name == "brief.md" and path.is_relative_to(ROOT / "docs/evaluation/artifacts"):
        return brief_origins.get(path.read_bytes(), path.parent)
    return path.parent


@pytest.mark.parametrize("location,changed,uses_source", [
    ("evaluation/artifacts/run", False, True),
    ("evaluation/artifacts/run", True, False),
    ("ordinary", False, False),
])
def test_frozen_brief_link_context_requires_exact_source_bytes(
    tmp_path, monkeypatch, location, changed, uses_source,
):
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    source = tmp_path / "docs/briefs" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("[Wave](wave.md)\n")
    (source.parent / "wave.md").write_text("The wave\n")
    frozen = tmp_path / "docs" / location / "brief.md"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(source.read_bytes() + (b"Changed\n" if changed else b""))
    origin = _relative_link_origin(frozen, {source.read_bytes(): source.parent})
    assert (origin / "wave.md").exists() is uses_source


def test_relative_links_between_documents_resolve():
    """Rule 3, the form the documentation actually uses most."""
    broken = []
    brief_origins = {
        path.read_bytes(): path.parent for path in (ROOT / "docs/briefs").glob("*.md")
    }
    for path in ROOT.rglob("docs/**/*.md"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        base = _relative_link_origin(path, brief_origins)
        for target in _MD_LINK.findall(path.read_text(encoding="utf-8", errors="replace")):
            resolved = (base / target).resolve()
            if not resolved.exists():
                inside = resolved.is_relative_to(ROOT)
                rel = resolved.relative_to(ROOT).as_posix() if inside else target
                if rel not in ALLOWED_DANGLING:
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, (
        "relative documentation links that do not resolve:\n  " + "\n  ".join(sorted(broken))
    )


def test_no_document_named_inside_an_immutable_record_has_been_moved_away():
    """Rule 2. A record cannot be corrected, so a path it names is pinned for good.

    Editing the path inside a record would change its `record_sha256`, and every record naming it as
    a predecessor binds that digest, so the correction cascades through the chain and cannot be
    made. The only way to keep a record honest is to leave the document where the record says it is.

    If a document here genuinely has to move, the honest options are to leave the original in place,
    or to accept and write down that the record now points at a path that is gone. There is no third
    option where the record is quietly fixed.
    """
    pinned: dict[str, list[str]] = {}
    for record in sorted((ROOT / "docs" / "evaluation").glob("*.json")):
        for ref in _referenced_paths(record.read_text(encoding="utf-8", errors="replace")):
            if ref.startswith("docs/evaluation/"):
                continue  # covered, with digests, by test_retained_evaluation_records.py
            pinned.setdefault(ref, []).append(record.name)

    assert pinned, "no record names a document path, which means this rule has stopped applying"
    missing = {
        ref: who for ref, who in pinned.items()
        if ref not in ALLOWED_DANGLING and not (ROOT / ref).exists()
    }
    assert not missing, (
        "these documents are named inside immutable evaluation records and are no longer at that "
        "path, so those records are now stranded and cannot be repaired:\n"
        + "\n".join(
            f"  {ref}  pinned by {', '.join(sorted(set(who)))}"
            for ref, who in sorted(missing.items())
        )
    )


@pytest.mark.parametrize("ref,reason", sorted(ALLOWED_DANGLING.items()))
def test_each_allowed_dangling_reference_is_still_dangling(ref: str, reason: str):
    """An allowlist nobody prunes becomes a lie about the tree.

    When one of these is finally written, this fails and the entry comes out, which is the only
    moment anybody would otherwise notice that a gap had closed.
    """
    assert not (ROOT / ref).exists(), (
        f"{ref} now exists, so remove it from ALLOWED_DANGLING. It was listed because: {reason}"
    )


def test_the_generated_inventory_matches_the_tree():
    """`docs/all-documents.md` is generated, so it can only be complete if nothing regenerates it.

    MEASURED 2026-09-09: the hand-maintained table this replaced listed 45 documents against 111 in
    the tree and never mentioned `docs/briefs/`. An index that is allowed to drift decays to
    whatever somebody last remembered to add, which is why the exhaustive half is generated and this
    test refuses a stale copy.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_docs_index", ROOT / "scripts" / "generate_docs_index.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    target = ROOT / "docs" / "all-documents.md"
    assert target.is_file(), "the inventory is missing; run scripts/generate_docs_index.py"
    assert target.read_text(encoding="utf-8") == module.render(), (
        "docs/all-documents.md is out of date. Run: uv run python scripts/generate_docs_index.py"
    )


def test_every_decision_record_appears_in_the_readme_table():
    """The hand-written half of the index, which no generator can produce.

    The ADR table carries what was DECIDED, one line each, and a status line extracted from the file
    cannot say that. So it stays hand-written, and this keeps it honest: MEASURED 2026-09-09, it had
    silently stopped at ADR-0017 while the tree held 22 records, so five decisions were invisible to
    every reader who started from the index.
    """
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    records = sorted(p.name for p in (ROOT / "docs" / "adr").glob("*.md"))
    assert records, "no decision records found, so this rule has stopped applying"
    missing = [name for name in records if f"](adr/{name})" not in readme]
    assert not missing, (
        "decision records absent from the table in docs/README.md:\n  " + "\n  ".join(missing)
    )
