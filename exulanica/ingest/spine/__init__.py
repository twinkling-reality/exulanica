"""The SQL the ingest path issues, one module per table's worth of queries.

``orimera/ingest/repository.py`` used to hold all of it: 730 lines and every statement the
photograph path sends to the spine, from the stage registry to the row counts. The class is
still there and still the only thing the ingest path imports, because the vocabulary the stages
speak is a real thing and splitting it would push the SQL into nine callers. What moved is the
SQL itself, so that a question about one table is answered by opening one file.

The modules, and the question each one answers:

===================== ============================================================
:mod:`scope`          Which workspace is this connection speaking for, and has it
                      said so out loud?
:mod:`stage_registry` What were each stage's version, model role and parameters
                      when it ran, for a reader who does not have the source?
:mod:`blobs`          Are these exact bytes already registered, and is anyone else
                      in the middle of destroying them?
:mod:`captures`       Which photograph is this, is it still live, and what does the
                      corpus know about when it was taken?
:mod:`tracks`         What does the container say about the samples in these bytes,
                      and to what wall-clock instant is sample zero pinned?
:mod:`spans`          Which row is this exact evidence address, created if this is
                      the first citation of it?
:mod:`tombstones`     Has the user asked for this content to be gone, and would the
                      write guards refuse this write?
:mod:`artifacts`      Has this stage already produced this output, and if it is
                      producing it now, under what identity?
:mod:`occurrences`    What did the detector see in this scene, at which address, and
                      under which identity key, with no column anywhere for a name?
:mod:`derived`        What was computed from what, so that deleting one input
                      invalidates exactly the objects that named it?
:mod:`inferences`     Which inference claims survived the write guards for these
                      captures, so a proposal is voted from what was persisted?
:mod:`reconstruction_scenes`
                      Which photographs were in the set a reconstruction ran over,
                      and which of them registered?
:mod:`reconstruction_jobs`
                      Which exact set is waiting for pose recovery, and which lease may
                      advance it?
:mod:`privacy`        Which exact source authorization and screening permitted geometry,
                      and did the exact ordered scene set pass the current policy?
:mod:`person_consent` Who is in this photograph, where, and what did each of them agree
                      to, with no column anywhere for anything that could recognise
                      them somewhere else?
:mod:`counts`         How many rows are in one of the thirteen tables this corpus may
                      be counted by, and in which scope is that number true?
===================== ============================================================

**Every public function here takes a** :class:`~exulanica.ingest.spine.scope.WorkspaceScope`
**as its first parameter**, and there is deliberately no way to build one without declaring a
workspace on the connection it wraps. 73 tables are under FORCE row-level security keyed on
``current_workspace()``, and the tombstone and epistemic guards do not merely read that setting,
they ``assert_workspace_context()`` and raise when it is absent. A module reachable with a bare
``psycopg.Connection`` would be a module reachable with an undeclared one. There is no type
checker configured for this project, so the rule is held by
``test_every_spine_function_takes_a_workspace_scope``, an AST sweep over these files, rather
than by a signature nobody verifies.

The sweep walks methods and nested functions as well as the top of each file, because a public
method on one of the row classes here would be a way in whose first parameter is ``self`` rather
than a scope. It walked module level only until a ``reload(self, connection, ...)`` was planted
on :class:`~exulanica.ingest.spine.artifacts.ArtifactRow` and the sweep called the package clean.

**This package deliberately re-exports nothing.** A caller reaches one facade,
:class:`~exulanica.ingest.repository.IngestRepository`, or it reaches the module that owns the
table. Two import paths to the same function would be two surfaces to keep honest, and the
tombstone race harness in ``tests/test_ingest_persistence.py`` intercepts by patching the
facade instance: a production caller that reached past it would be raced by nothing.
"""

from __future__ import annotations

__all__: list[str] = []
