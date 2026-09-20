"""Every documentation path this repository names must be in this repository, and records must
never be stranded.

**Rule 0, which decides what every other rule here means.** A documentation link is a claim about a
commit, not about a filesystem. ``Path.exists()`` answers a different question, and the two answers
agreed only in the one checkout where the operator's untracked working files happen to sit.
MEASURED 2026-09-19 at 15e8198c, the guard as it stood then, against two checkouts of that one
commit: asking the disk reported 36 unresolved paths in a worktree holding only what the commit
holds, and none in a worktree carrying the operator's untracked documents beside it, which is what
the operator's own checkout carries. So the suite held a failure nobody could reproduce or repair
anywhere but one directory. Asking ``git ls-files`` reports the same answer in both, and that
answer is the true one, which is that this repository names documents it does not contain. So
every rule below resolves against the files git holds, and the question the guard asks is the only
one a reader has, which is whether a clone of this repository can follow the pointer.

That also decides which documents a rule reads. Reading the disk meant one of those two checkouts
scanned 232 markdown documents under ``docs/`` and the other scanned 110, so one commit was
checked against two different corpora and neither count was a fact about the repository.

**Rule 1, ordinary link rot.** Nothing checked a markdown link or a ``docs/...`` string in a
comment before 2026-09-09, and the cost of that was already paid: ``adr/0008-generated-geometry.md``
points at ``license-matrix.md:441``, which lands on a blank line, and nobody noticed. MEASURED
2026-09-09 across the tree: 1,319 references to 740 distinct documentation paths, ten of which did
not resolve.

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

WHAT IS ALLOWED TO DANGLE, and why two lists rather than one. Every unresolved reference is named
below with its reason, so a new one fails loudly, and the two lists are separate because the right
response to each is the opposite of the other. ``ALLOWED_DANGLING`` is a reference this tree cannot
satisfy, which is usually a document that ought to exist and does not, and when somebody finally
writes it the entry comes out. Two of those are more useful than a clean list would be, because a
brief that names a deliverable which was never produced is evidence that commissioned work did not
close out, and hiding that behind a clever exemption for briefs would throw away the signal. The
rest of that list is not waiting for anybody: a placeholder in a document's own instructions, or a
path a test builds inside its sandbox, neither of which is a document and neither of which will
ever arrive. ``KEPT_OUT_OF_THE_REPOSITORY`` is not a gap either: those documents
exist and a deliberate decision keeps them out of git. If one of them ever becomes tracked, that is
a publication, and the failure says so rather than telling a reader to go and write the file.

Neither list is a filter. Both name every path individually, because a prefix rule over
``docs/briefs/`` would have swallowed the two never-produced deliverables this file exists to keep
visible, and a prefix rule over ``docs/evaluation/`` would swallow the next mistyped record name.

A reason here names documents by what they are rather than by their path when the path is one this
repository does not hold. The first version of this file spelled them out, and the spelling was
itself a reference, so the guard generated three of its own exclusions and then required them to be
explained.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

_TEMPLATE = "template text in the document's own instructions"

_SANDBOX = (
    "a path a test builds under its own tmp_path root, so it is written and read inside that "
    "test and is never a document in this tree"
)

#: A reference this tree cannot satisfy, and why it is not a defect to be fixed here. Most are a
#: document that ought to exist and does not; the rest are not documents at all.
ALLOWED_DANGLING: dict[str, str] = {
    "docs/evaluation/2026-09-19-control.json": _SANDBOX,
    "docs/evaluation/2026-09-19-corridor-under-test.json": _SANDBOX,
    "docs/evaluation/2026-09-12-earth-interactive-foundation.json": (
        "reserved successor output in the immutable dispatched Earth correction brief; "
        "the unaccepted Earth lane has not been integrated. Do not invent a result to fill it."
    ),
    "docs/evaluation/NEW-asset-read-currency.json": _TEMPLATE,
    "docs/evaluation/NEW-personal-admission-flow.json": _TEMPLATE,
    "docs/evaluation/NEW-screening-currency.json": _TEMPLATE,
    "docs/evaluation/PRIOR.json": "a placeholder in the recorder's usage string, not a real path",
    "docs/recovery-drill-2026-09-08.md": (
        "the 2026-09-08 isolated recovery drill brief names this as a deliverable and it was "
        "never produced. Kept visible on purpose: the brief is a plan and the gap is the finding."
    ),
    "docs/retained-activation-2026-09-08.md": (
        "the 2026-09-08 retained activation brief names it as a deliverable and it was "
        "never produced. Same reason as above."
    ),
    "docs/evaluation/2026-09-08-isolated-recovery-drill.json": (
        "the record its brief commissioned, never written; the work did not close out"
    ),
    "docs/evaluation/2026-09-08-retained-activation.json": (
        "the record its brief commissioned, never written; the work did not close out"
    ),
    "docs/generated-tier-disclosure.md": (
        "a 2026-09-08 integration record describes a branch that created this file; it is not in "
        "this tree, so either the branch did not land or it was renamed on the way in"
    ),
}

_WHY_OPERATOR_PROCESS = (
    "operator process, kept on disk for the evidence tests and held out of the repository by a "
    "rule in the tracked .gitignore, which a test below reads back from git rather than trusting "
    "this sentence. A reader who clones this repository cannot follow the pointer."
)

#: Named by the tree, held out of it by .gitignore. The repository states this decision itself.
_OPERATOR_PROCESS: tuple[str, ...] = (
    "docs/briefs/2026-09-12-helsinki-terminal-lod-successor.md",
    "docs/briefs/2026-09-12-helsinki-visual-feasibility.md",
    "docs/briefs/2026-09-12-melbourne-c4-29-visual-feasibility.md",
    "docs/frontier-demonstration.md",
    "docs/goal-brief-2026-09-05-unblocked-backend-program.md",
    "docs/goal-brief-2026-09-08-remaining-work.md",
    "docs/judge-access.md",
    "docs/phase-10-tickets.md",
    "docs/reconstruction-throughput.md",
    "docs/records/2026-09-08-asset-read-currency-investigation.md",
    "docs/records/2026-09-08-scene-inspection.md",
    "docs/reference-gpu-compute.md",
)

_WHY_LOCAL_CAMPAIGN = (
    "a local-only evaluation campaign. docs/README.md says not to git add a campaign unless it "
    "belongs on the public catalog, and this one was not added, so the record and the artifacts "
    "it binds exist only on the machine that ran it. Nothing tracked records which campaigns "
    "those are, because the list lives in the operator's own .git/info/exclude and that file is "
    "not in the repository, so this tuple is the only statement of it a clone can read."
)

#: Named by the tree, never committed. Unlike the group above, no tracked file explains these.
_LOCAL_CAMPAIGN: tuple[str, ...] = (
    "docs/evaluation/2026-09-09-companion-memory.json",
    "docs/evaluation/2026-09-09-companion-question.json",
    "docs/evaluation/2026-09-09-graph-read-memo.json",
    "docs/evaluation/2026-09-10-companion-prompts.json",
    "docs/evaluation/2026-09-10-companion-proposals-on-the-copy.json",
    "docs/evaluation/2026-09-10-companion-proposals.json",
    "docs/evaluation/2026-09-10-drafting-reliability.json",
    "docs/evaluation/2026-09-11-companion-matching.json",
    "docs/evaluation/2026-09-11-developer-proof.json",
    "docs/evaluation/2026-09-11-first-place.json",
    "docs/evaluation/2026-09-11-observation-resolve.json",
    "docs/evaluation/2026-09-12-environment-source-admission.json",
    "docs/evaluation/2026-09-12-helsinki-terminal-lod-successor.json",
    "docs/evaluation/2026-09-12-helsinki-visual-feasibility.json",
    "docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json",
    "docs/evaluation/artifacts/2026-09-09-companion-question/ask-unrelated.response.json",
    "docs/evaluation/artifacts/2026-09-09-companion-question/packet-probe.response.json",
    "docs/evaluation/artifacts/2026-09-11-first-place/companion/ask-2.json",
)

#: A document this repository names and deliberately does not contain, and who decided that.
KEPT_OUT_OF_THE_REPOSITORY: dict[str, str] = {
    **dict.fromkeys(_OPERATOR_PROCESS, _WHY_OPERATOR_PROCESS),
    **dict.fromkeys(_LOCAL_CAMPAIGN, _WHY_LOCAL_CAMPAIGN),
}

#: Every path a rule may leave unresolved. A reference outside this set is a defect.
_EXPLAINED = ALLOWED_DANGLING.keys() | KEPT_OUT_OF_THE_REPOSITORY.keys()

_TEXT_SUFFIXES = {
    ".py", ".md", ".toml", ".json", ".mjs", ".js", ".ts", ".tsx", ".cjs", ".yml", ".yaml",
}

#: A path inside a URL belongs to somebody else's repository. MEASURED: without this, the external
#: `deep-person-reid` model zoo link in evaluation-methodology.md reads as a local dangling path.
_URL = re.compile(r"https?://\S+")
_DOC_PATH = re.compile(r"docs/[A-Za-z0-9][A-Za-z0-9/._-]*\.(?:md|json|patch|txt|png|py)")
_MD_LINK = re.compile(r"\]\(([A-Za-z0-9][A-Za-z0-9/._-]*\.md)(?:#[^)]*)?\)")


def _tracked() -> frozenset[str]:
    """Every path this repository holds, which is the only thing a documentation link can name.

    Tracked, not present, in both directions. The gitignored working areas hold private notes that
    name documents which never existed in this tree, and a gate that failed on a scratch directory
    nobody committed would be measuring the author's desk: MEASURED 2026-09-09, `.orimera/` named
    three such paths and failed the merged suite. That half was already right. The other half is
    what a named path is allowed to resolve TO, and asking the disk there was wrong for the same
    reason in the other direction. A skip-list of directory names is replaced by reading the
    index, because git lists none of them.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True
    ).stdout.decode()
    return frozenset(filter(None, listed.split("\0")))


def _text_files() -> list[Path]:
    """The tracked text files a reference can be written in."""
    return [
        ROOT / rel
        for rel in sorted(_tracked())
        # The artifact tree is large and holds captured logs rather than references.
        if not rel.startswith("docs/evaluation/artifacts/") and Path(rel).suffix in _TEXT_SUFFIXES
    ]


def _referenced_paths(text: str) -> set[str]:
    return set(_DOC_PATH.findall(_URL.sub(" ", text)))


def _absolute_references() -> dict[str, list[str]]:
    """Every ``docs/...`` path the repository names, and the tracked files that name it."""
    named: dict[str, list[str]] = {}
    for path in _text_files():
        rel = path.relative_to(ROOT).as_posix()
        for ref in _referenced_paths(path.read_text(encoding="utf-8", errors="replace")):
            named.setdefault(ref, []).append(rel)
    return named


def _relative_link_origin(path: Path, brief_origins: dict[bytes, Path]) -> Path:
    """An exact frozen prompt retains the source document's relative-link context.

    Only artifact brief.md copies qualify. Complete byte equality verifies the origin;
    copying a rendered title may omit its initial heading marker and final newline.
    A changed body or an ordinary document must resolve from its own directory.
    """
    if path.name == "brief.md" and path.is_relative_to(ROOT / "docs/evaluation/artifacts"):
        content = path.read_bytes()
        for candidate in (content, b"# " + content, b"# " + content + b"\n"):
            if candidate in brief_origins:
                return brief_origins[candidate]
    return path.parent


def _relative_references() -> list[tuple[str, str, str]]:
    """Every relative markdown link between tracked documents, as (document, link, target).

    The target is repo relative and is computed rather than resolved on disk, for the reason in
    rule 0. A link that climbs out of the repository keeps its written form as the target, which
    is what a reader would have to follow. MEASURED 2026-09-19 at 15e8198c: the frozen brief origin
    above has nothing tracked to work on, because none of the nineteen artifact brief.md copies and
    only two of the sixty-one briefs are in the repository, so the parametrised tests below are
    what covers it.
    """
    tracked = _tracked()
    documents = sorted(p for p in tracked if p.startswith("docs/") and p.endswith(".md"))
    brief_origins = {
        (ROOT / p).read_bytes(): ROOT / os.path.dirname(p)
        for p in tracked
        if p.startswith("docs/briefs/") and p.endswith(".md")
    }
    found = []
    for rel in documents:
        path = ROOT / rel
        base = _relative_link_origin(path, brief_origins).relative_to(ROOT).as_posix()
        for link in _MD_LINK.findall(path.read_text(encoding="utf-8", errors="replace")):
            target = os.path.normpath(os.path.join(base, link))
            found.append((rel, link, link if target.startswith("..") else target))
    return found


def test_every_documentation_path_named_anywhere_in_the_repository_resolves():
    """Rule 1. A pointer nobody can follow is worse than no pointer, because it looks like one."""
    tracked = _tracked()
    broken = {
        ref: who
        for ref, who in _absolute_references().items()
        if ref not in _EXPLAINED and ref not in tracked
    }
    assert not broken, (
        "documentation paths this repository names and does not contain:\n"
        + "\n".join(
            f"  {ref}  named by {', '.join(sorted(set(who))[:3])}"
            for ref, who in sorted(broken.items())
        )
    )


@pytest.mark.parametrize("location,changed,heading_removed,newline_removed,uses_source", [
    ("evaluation/artifacts/run", False, False, False, True),
    ("evaluation/artifacts/run", True, False, False, False),
    ("ordinary", False, False, False, False),
    ("evaluation/artifacts/run", False, True, False, True),
    ("evaluation/artifacts/run", True, True, False, False),
    ("evaluation/artifacts/run", False, True, True, True),
    ("evaluation/artifacts/run", True, True, True, False),
])
def test_frozen_brief_link_context_requires_exact_source_bytes(
    tmp_path, monkeypatch, location, changed, heading_removed, newline_removed, uses_source,
):
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    source = tmp_path / "docs/briefs" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source\n[Wave](wave.md)\n")
    (source.parent / "wave.md").write_text("The wave\n")
    frozen = tmp_path / "docs" / location / "brief.md"
    frozen.parent.mkdir(parents=True)
    content = source.read_bytes()[2:] if heading_removed else source.read_bytes()
    content += b"Changed\n" if changed else b""
    frozen.write_bytes(content[:-1] if newline_removed else content)
    origin = _relative_link_origin(frozen, {source.read_bytes(): source.parent})
    assert (origin / "wave.md").exists() is uses_source


def test_relative_links_between_documents_resolve():
    """Rule 3, the form the documentation actually uses most."""
    tracked = _tracked()
    broken = [
        f"{document} -> {link}"
        for document, link, target in _relative_references()
        if target not in tracked and target not in _EXPLAINED
    ]
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
    tracked = _tracked()
    records = sorted(
        rel for rel in tracked
        if rel.startswith("docs/evaluation/")
        and rel.endswith(".json")
        and not rel.startswith("docs/evaluation/artifacts/")
    )
    assert records, "no record is in the repository, which means this rule has stopped applying"
    pinned: dict[str, list[str]] = {}
    for rel in records:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for ref in _referenced_paths(text):
            if ref.startswith("docs/evaluation/"):
                continue  # covered, with digests, by test_retained_evaluation_records.py
            pinned.setdefault(ref, []).append(os.path.basename(rel))

    assert pinned, "no record names a document path, which means this rule has stopped applying"
    missing = {
        ref: who for ref, who in pinned.items()
        if ref not in _EXPLAINED and ref not in tracked
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
    assert ref not in _tracked(), (
        f"{ref} is in the repository now, so remove it from ALLOWED_DANGLING. "
        f"It was listed because: {reason}"
    )


def test_nothing_kept_out_of_the_repository_has_been_committed():
    """The mirror of the rule above, and the opposite instruction.

    These documents are not missing, they are withheld, so the answer to this failing is never to
    go and write the file. Either the decision changed, in which case the entry comes out, or
    something private was published by accident, in which case the commit is the thing to fix.
    """
    committed = sorted(KEPT_OUT_OF_THE_REPOSITORY.keys() & _tracked())
    assert not committed, (
        "these are listed as deliberately held out of the repository and are now committed:\n  "
        + "\n  ".join(committed)
        + "\nIf that was intended, remove the entry. If it was not, this is a publication."
    )


def test_every_withheld_document_is_still_named_by_some_other_file():
    """An exception that outlives the reference it explains stops describing anything.

    Each of these entries exists because a tracked file points at a document the repository does
    not carry. When the last such file stops pointing at it, the entry explains nothing and the
    next reader has to work out what it was for. This file does not count as a namer, or the list
    would keep itself alive: every path here appears in it, as its own key.
    """
    mine = Path(__file__).resolve().relative_to(ROOT).as_posix()
    named = {ref for ref, who in _absolute_references().items() if set(who) - {mine}}
    named.update(target for _, _, target in _relative_references())
    orphaned = sorted(KEPT_OUT_OF_THE_REPOSITORY.keys() - named)
    assert not orphaned, (
        "nothing in the repository names these any more, so the entries holding them out are "
        "stale:\n  " + "\n  ".join(orphaned)
    )


def test_each_operator_process_reference_is_held_out_by_a_tracked_ignore_rule():
    """The reason beside those entries is a claim about .gitignore, so read .gitignore.

    The distinction between the two tuples is the whole reason there are two, and prose does not
    hold a distinction. git is asked which rule excludes each path, and the rule counts only if it
    lives in a file this repository tracks: an answer out of `.git/info/exclude` is an answer about
    one machine, which is the mistake rule 0 is about.
    """
    tracked = _tracked()
    listed = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--stdin", "-z"],
        cwd=ROOT, input="\0".join(_OPERATOR_PROCESS).encode(), capture_output=True,
    ).stdout.decode().split("\0")
    source = {listed[i + 3]: listed[i] for i in range(0, len(listed) - 3, 4)}
    unexplained = {
        ref: source.get(ref, "no ignore rule matches it")
        for ref in _OPERATOR_PROCESS
        if source.get(ref) not in tracked
    }
    assert not unexplained, (
        "these are listed as held out by a tracked ignore rule and no tracked rule covers them:\n"
        + "\n".join(f"  {ref}  excluded by: {why}" for ref, why in sorted(unexplained.items()))
    )


def test_the_lists_of_unresolved_references_have_not_grown_silently():
    """Both lists shorten on their own and neither shortens or lengthens without being edited.

    Every other test here prunes: an entry whose document arrives, or whose last reference goes
    away, fails and comes out. Nothing makes adding one cost anything, and a list that grows
    quietly is how a guard turns into a filter. MEASURED 2026-09-19 at 775d44f8: this repository
    names 48 paths under ``docs/`` that it does not hold, 36 of them documents a decision keeps
    out, six documents nobody wrote, and six that were never documents at all, being three
    template placeholders, one placeholder in a usage string, and two paths that tests build
    inside their own sandboxes.

    MEASURED AGAIN 2026-09-19 after the four ``docs/patches`` diffs were published: 44, because
    the operator process tuple lost those four. A number here falling is the shape this file
    wants, and the commit that moves it says which documents arrived.

    Adding an entry means this repository names one more document it does not contain. That is a
    fact about the repository rather than about a test, so it is worth a line in whatever record
    the change belongs to, and the number here is edited deliberately in the same commit.
    """
    assert (len(ALLOWED_DANGLING), len(_OPERATOR_PROCESS), len(_LOCAL_CAMPAIGN)) == (12, 12, 18)
    assert len(KEPT_OUT_OF_THE_REPOSITORY) == len(_OPERATOR_PROCESS) + len(_LOCAL_CAMPAIGN), (
        "a path is in both tuples, and dict.fromkeys silently kept one reason for it"
    )
    assert not ALLOWED_DANGLING.keys() & KEPT_OUT_OF_THE_REPOSITORY.keys(), (
        "a path cannot be both a document nobody wrote and a document deliberately withheld"
    )


def test_the_index_and_this_checkout_agree_about_the_files_this_guard_reads():
    """A half set up checkout does not fail, it reports smaller numbers.

    Everything above counts references found in tracked files, which are read from disk. A tracked
    file missing from the working tree would raise inside a helper several tests share, so it is
    named here instead, and a checkout that disagrees with its own index says so once.
    """
    absent = [path.relative_to(ROOT).as_posix() for path in _text_files() if not path.is_file()]
    assert not absent, (
        "git holds these and this checkout does not, so every count in this file would be low:\n  "
        + "\n  ".join(absent)
    )


def test_the_generated_inventory_matches_the_tree():
    """`docs/all-documents.md` is generated. A catalog that is allowed to drift decays."""
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
    catalog = target.read_text(encoding="utf-8")
    assert "](briefs/" not in catalog
    assert "](records/" not in catalog
    assert "](patches/" not in catalog
    assert "](evaluation/" not in catalog


def test_every_decision_record_appears_in_the_readme_table():
    """The hand-written half of the index, which no generator can produce.

    The ADR table carries what was DECIDED, one line each, and a status line extracted from the file
    cannot say that. So it stays hand-written, and this keeps it honest: MEASURED 2026-09-09, it had
    silently stopped at ADR-0017 while the tree held 22 records, so five decisions were invisible to
    every reader who started from the index.
    """
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    records = sorted(
        os.path.basename(rel) for rel in _tracked()
        if rel.startswith("docs/adr/") and rel.endswith(".md")
    )
    assert records, "no decision records found, so this rule has stopped applying"
    missing = [name for name in records if f"](adr/{name})" not in readme]
    assert not missing, (
        "decision records absent from the table in docs/README.md:\n  " + "\n  ".join(missing)
    )
