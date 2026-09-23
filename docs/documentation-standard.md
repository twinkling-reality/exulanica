# Documentation standard

Documentation lets a person or agent find the owner of a question, understand the supported
behavior, make a change and verify it without reconstructing project history. This standard owns
filing, review and maintenance. The [ownership map](navigation.json) assigns each public document
a subject home, role and responsibility; the [catalog](all-documents.md) presents that map.

## Quality rubric

Review each dimension as **meets**, **partial** or **fails**, with a concrete example and required
correction for a partial or failing result. Do not average a factual or privacy failure into a
passing score. A document is ready when the applicable criteria meet the standard; mark a criterion
inapplicable with a reason rather than inventing evidence.

| Dimension | Acceptance criterion | Verification |
| --- | --- | --- |
| Ownership | One document owns each behavior or decision. Its title and opening state that responsibility. Other documents summarize and link instead of maintaining competing rules. | Review its catalog responsibility and neighboring contracts; check for conflicting instructions. |
| Accuracy | Behavior, requirements, hypotheses and measured results are distinguishable. Implementation claims resolve to code or scoped execution evidence. | Trace changed claims to definitions, schemas, callers or records. A link or test pass alone does not establish a claim. |
| Navigation | A reader can get from the hub to the relevant owner through a task link or subject catalog. Paths and section links resolve in a clone. | Follow representative reader tasks; run link, ownership-map and catalog checks. |
| Focus | A document serves one audience task or coherent responsibility. It does not require unrelated history to explain the operation. | Remove duplicated prose; separate a guide from a contract when they answer different questions. Long contracts need a local contents list or a clear section map. |
| Lifecycle | The change updates existing owners, defines remaining limits and preserves required history. Public docs contain no private working notes. | Review the full diff, incoming references and evidence bindings before moving or retiring a file. |
| Maintainability | Commands and interfaces have one source of truth. A meaningful check catches mechanical drift; semantic review remains explicit. | Run focused checks and inspect their coverage. Do not add brittle tests for phrasing or a test that merely restates a table. |

File count, word count, nesting depth and a green suite are not quality scores. Fewer files help
only if readers can still find a focused answer. More folders help only when they express stable
responsibilities. No checklist proves the entire system correct; report the scope actually reviewed.

## Reading and authority

The short reading path is the root README, the [documentation hub](README.md), then the owner of
the task. Product orientation uses [product direction](product-direction.md) and
[architecture](architecture-overview.md); implementation work adds only the relevant contract and
its source. Do not require every contributor or agent to read the full catalog.

| Role | Owns | Does not own |
| --- | --- | --- |
| Overview | Product scope, system shape or navigation | A second copy of detailed runtime status |
| Guide | A user or developer task, prerequisites, steps and expected outcome | Undocumented API behavior or a competing specification |
| Contract | Invariants, supported operations, failure semantics and boundaries for one responsibility | Release diaries, assignments or a growing list of completed tasks |
| Reference | Lookups, selections, measurements or rationale used by a named task | Product scope or an unconditional override of newer evidence |
| Standard | Rules for contributing and reviewing work | Per-run instructions |
| Archive | Historical context and links to successor owners | Active requirements or implementation claims |
| Decision record | A durable choice, rejected alternatives and the contract it affects | An alternate product specification |
| Evaluation record | An immutable account of one execution and its bound artifacts | Proof about inputs, versions or deployments it did not exercise |

[Product direction](product-direction.md) owns scope and acceptance order. Living contracts own
their declared behavior. Code and execution evidence establish implementation facts. When these
conflict, record and resolve the discrepancy against the actual source; do not silently promote an
aspiration or treat an old runtime observation as a universal override. A contract change can
intentionally precede implementation only when the gap and acceptance criterion are explicit.

## Structure and filing

| Location | Contents | Rule |
| --- | --- | --- |
| Root README | Product introduction and minimal setup | Link to deeper documents instead of duplicating them |
| Documentation hub | Reader tasks and subject entry points | Keep short; the generated catalog owns the inventory |
| `docs/capabilities/` | Product and external developer guides | Explain usable behavior and material limits |
| Existing `docs/` contract paths | Living contracts and reference | Retain established paths, especially those named by immutable evidence |
| `docs/reference/<subject>/` | Additional specialist references when an existing owner cannot contain them coherently | Use one stable subject level matching the ownership map; register every document |
| `docs/adr/` | Durable architectural decisions | Stable numbers; link the affected living contract |
| `docs/evaluation/` | Execution records and bound artifacts | Immutable; do not edit, move, reformat or rehash |
| Ignored `.exulanica/briefs/` | Working notes, handoffs and assignments | Never stage or publish; promote verified reusable facts into their owner |

Existing retained briefs, patches and artifacts are not an onboarding path. Do not move historical
private trees blindly. A path named by an immutable record remains available at that path. A bound
artifact's bytes also remain unchanged. A mutable document merely referenced by a record may evolve
without claiming that its edited text was the text evaluated by that execution.

Physical nesting is not a reason to break a stable address. The subject hierarchy in the catalog
organizes existing root paths without creating duplicate contract files. Avoid a folder per phase,
agent, release or work session. Add a subject only for a distinct responsibility that existing
subjects cannot represent, not for a new task.

## Change workflow

1. **Find the owner.** Start from the hub or catalog. Read the relevant contract and the source
   that implements the behavior. Check working-tree changes before editing shared files.
2. **Choose the smallest durable update.** Revise the owner in place. Add a document only when it
   has an independent reader task or responsibility; state its role, subject and scope in the map.
3. **Write the final behavior.** Replace superseded prose rather than appending a correction below
   a contradictory claim. Preserve material limitations and link evidence at its actual scope.
4. **Handle history deliberately.** Keep decision rationale in a decision record, results in their
   records and session notes in ignored briefs. A fixed Git revision can retain obsolete narrative
   without leaving a second active specification. Never use this to remove bound evidence.
5. **Update navigation.** Edit `docs/navigation.json` when ownership or membership changes. For a
   move, inspect incoming references, anchors, code references and immutable bindings first. Keep
   required addresses or choose a different consolidation. Do not leave unexplained redirects.
6. **Verify and report.** Run the applicable checks below and review changed claims. Report the
   scope, behavior changed, evidence used and material gaps. Do not equate mechanical checks with
   a complete semantic audit.

An agent handoff should identify changed files, source/evidence links, decisions still needed and
checks performed. It belongs in ignored working notes. Do not append the handoff, personal
conversation or test-run diary to a public contract. A useful discovery becomes a focused change
to its owner, with its supporting evidence.

## Document shape

Use the shape appropriate to the role; empty template sections are unnecessary.

- **Guide:** purpose, prerequisites, steps, expected result, common failures, links to contracts.
- **Contract:** scope and owner, invariants, data/operations, failures and authorization, compatibility,
  implementation boundaries, supporting code and evidence. Group by behavior, not implementation date.
- **Reference:** scope, organized facts, provenance and limitations.
- **Archive:** historical scope, fixed source revision and successor owners.
- **Decision:** choice, rationale, alternatives, consequences and affected contract.

Long technical contracts remain modular when sections have coherent responsibilities and direct
links. Split at an independently changing boundary, not at an arbitrary word count. Avoid both a
single project-sized specification and dozens of fragments needed to understand one operation.

## Prose and claims

Identify a thing by what it is, not by when someone looked at it. Titles name subjects, not
sessions. Prefer present tense and concrete behavior. Avoid freshness claims such as "currently",
"new", "soon" and "now supports". Use **requirement**, **implemented boundary**, **hypothesis** or
**measured result** where readers need the distinction; these labels are not substitutes for proof.

Dates belong to measurements and decisions. Versions belong to actual contracts, model revisions
and artifacts. Do not use a date or version number merely to imply that prose is up to date.
Measurements identify their inputs, revision, method, outcome and limits. Quote a test count only
with a date and commit, or omit it.

Use descriptive headings, plain language and parallel tables when comparison helps. Define product
terms before relying on them. Keep technical details in product-facing copy only where they help a
person decide. No em dash. Preserve technical identifiers even when their spelling differs from
prose conventions. Explain a negative boundary when readers could otherwise assume a capability.

Verify code paths, commands, route names and configuration against their definitions. Correct a
false statement only with evidence; otherwise record the unresolved discrepancy. Do not rewrite
facts to make prose smoother. Source and permission requirements remain visible after consolidation.

## Evidence labels

Existing technical documents use the following labels. They apply to the adjacent claim, not the
whole file or every later revision. Prefer clear scoped prose over labeling every sentence.

| Label | Required meaning |
| --- | --- |
| VERIFIED | A primary source or executed measurement supports the stated claim within its recorded scope. |
| DECISION | A chosen rule and its rationale, including consequential rejected alternatives. |
| ASSUMPTION | An unvalidated proposition and the evidence needed to settle it. |
| OPEN | An unresolved question; no implied supported capability. |
| CLOSED | A resolved question with the decision, implementation or evidence that closes it. |
| CORRECTED | A factual correction grounded in source, with history retained where material. |

A section marked historical preserves these labels as statements about the original research.
It does not silently recertify a price, provider, runtime, legal interpretation or capability.

## Checks

The catalog lists repository-held documents. New public files must be registered and staged before
regeneration so the same catalog is produced in a fresh clone. Stage explicit intended paths only;
staging is not authorization to commit. Ignored working notes never enter the catalog.

```bash
uv run python scripts/generate_docs_index.py
uv run pytest -q tests/test_documentation_links.py tests/test_documentation_structure.py
uv run python scripts/generate_docs_index.py --check
git diff --check
```

These checks cover file and section links, code-path references, classified ownership, decision
inventory and generated output. They do not verify remote websites, every prose assertion,
operational command or visual quality. Verify examples at the affected boundary without running
paid services, changing user data or repeating unrelated suites just for a documentation edit.
Use the existing publication and naming guards before publishing, according to repository policy.
