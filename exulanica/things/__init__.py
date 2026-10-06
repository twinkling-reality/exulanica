"""Things: what each thing in a world is, can do and lets others do, apart from how it looks.

A thing is anything addressable in a world, a person, a creature, an object or a visitor from
another program. This package holds the data that says what each kind of thing is (thing kinds,
profile ``exulanica.thing-kind/v1``), the vocabularies a kind is read against (body plans,
abilities, offers, look kinds), the looks a thing may wear (``exulanica.look/v1``), the one origin
record every kind, look and crossing carries (``exulanica.origin/v1``), the translation manifest
every import and crossing writes, and the looks this repository authors. docs/things-contract.md
owns the contract.

Pure: it opens no database or store and asks no model, which an import contract holds.
"""
