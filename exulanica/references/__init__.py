"""Reference material that helps a model draft a world: sources, the outgoing-query boundary, notes.

A world is drafted from a person's words, and drafts better from short notes about what the things
in those words look like. This package holds the parts of that which need no database:

* :mod:`~exulanica.references.catalogs` reads the reference sources, the note aspects and the
  outgoing-query screen as catalog data (``assets/catalogs/reference-sources/``);
* :mod:`~exulanica.references.boundary` is the one way a search subject becomes a query that may
  leave: the workspace's hosted request policy, then the screen;
* :mod:`~exulanica.references.adapters` holds one adapter per source, and nothing else sends;
* :mod:`~exulanica.references.notes` keeps a drafted note only if it copies no run of a source's
  words and carries nothing personal;
* :mod:`~exulanica.references.bundle` is the reference bundle a drafter receives, and
  :mod:`~exulanica.references.render` the block its prompt carries.

What a web source returns lives only in the memory of the job that asked: no result text, title,
address or picture is kept, shown or exported, because the source's terms give no right to.
"""
