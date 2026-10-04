"""Pydantic model to ``json_schema`` strict, the only mechanism allowed to write canonical state.

Three mechanisms were measured against this endpoint. Exactly one is used:

===================================================  =========================================
``response_format {type: json_schema, strict: true}``  valid JSON. This module builds it.
``response_format {type: json_object}``                valid JSON, but no schema enforced.
top-level ``guided_json``                              **silently ignored**, returns prose, 200.
===================================================  =========================================

The third is the reason this module exists as a chokepoint rather than a helper. A parameter
that is accepted and ignored produces an HTTP 200 with a plausible prose answer, so a pipeline
using it looks like it works while enforcing nothing at all. ``exulanica.models.client`` refuses to
send it, and refuses any ``response_format`` this module did not build.

Strict mode has requirements Pydantic's own schema does not meet, so ``strict_json_schema``
hardens the output: every object gets ``additionalProperties: false``, every property is listed
in ``required``, and annotations that carry no constraint (``title``, ``default``) are dropped so
the payload is deterministic. Listing every property as required is not a stylistic choice; it is
what strict mode demands. Fields that are genuinely optional must therefore be typed to admit
``None``, and the model can then return an explicit null rather than omitting the key, which is
the difference between "the model did not find one" and "the model forgot".

A hand-written schema is supported too, through ``response_format_for_schema``. The vision
observation schema is written by hand deliberately: a generated one carries ``$defs`` and
``anyOf``, which a strict-mode endpoint may reject or, worse, accept while ignoring. The
chokepoint is the same either way, because the client refuses any ``response_format`` that is
not ``json_schema`` with ``strict: true``.

``extract_json_object`` is the reader half. It exists because of `runtime-verification.md` section
5:
the reasoning models write scratch work **inline in ``message.content``** and it cannot be
switched off. Tagged scratch work is removed upstream by ``exulanica.models.reasoning``; untagged
prose in front of the object is not, and ``json.loads`` on the whole body fails on exactly the
models this project runs.

**The extractor does not guess which object is the answer.** It used to take the first balanced
object in the body, and a measured Nemotron response of the shape ``a minimal example would be
{"scene_description": "PLACEHOLDER FROM MY SCRATCH WORK"} ... my real answer is:
{"scene_description": "A waterfall in a forest."}`` therefore returned the placeholder. The
placeholder is schema-valid, so every downstream check passed it and it was persisted as an
assertion about a photograph. Taking the last object instead would have got that one case right
and is still a guess: nothing in the body says which object is the answer, and the models are
free to write their scratch work after their conclusion.

So the rule here is:

1.  Reasoning that carries a delimiter is stripped before extraction ever runs. That is
    ``exulanica.models.reasoning``, and it is the only reliable separation available.
2.  What survives is scanned for **every** top-level balanced object that parses. Candidates
    that are equal carry no ambiguity and collapse to one.
3.  Exactly one distinct candidate is the answer. Zero is a failed call. **Two or more is
    refused**, because picking one would be inventing the provenance of a fact.

The scan is only reached when the body is not itself one JSON document. A reply that parses
cleanly as JSON and is an array or a scalar is refused before the scan runs: that is not an
answer wrapped in prose, it is the wrong type, and reaching inside it for the object it happens
to contain would accept a shape the request never asked for. The distinction is exact rather
than usual, because ``json.loads`` succeeds on the whole body only when there is nothing else in
it, so no body the scanner exists for can reach this refusal.

Refusal costs a retry. A guess costs a memory that never happened, attributed to nobody.

``validate_against_schema`` is the other half of the reader. Sending
``response_format {json_schema, strict}`` is a request, not a guarantee: a server that ignores it
answers HTTP 200 with a well-formed object of the wrong shape, and the ``guided_json`` result in
`runtime-verification.md` section 6 is that exact failure one layer down. The payload is therefore
validated locally against the byte-identical schema that was sent, so the enforcement does not
depend on the endpoint honouring it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel

from exulanica.models.errors import (
    AmbiguousStructuredOutputError,
    SchemaViolationError,
    StructuredOutputError,
)

__all__ = [
    "extract_json_object",
    "json_object_candidates",
    "response_format_for",
    "response_format_for_schema",
    "strict_json_schema",
    "validate_against_schema",
]

#: Keys that carry documentation rather than constraint. Dropped so two runs of the same model
#: produce byte-identical request payloads, which is what makes the response cache key stable.
_DROP: Final = frozenset({"title", "default", "examples", "$comment", "deprecated", "readOnly"})

_CONTAINER_KEYS: Final = ("items", "additionalItems", "contains", "not")
_LIST_KEYS: Final = ("anyOf", "oneOf", "allOf", "prefixItems")
_MAP_KEYS: Final = ("properties", "$defs", "definitions", "patternProperties")


def _harden(node: Any) -> Any:
    if isinstance(node, list):
        return [_harden(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {k: v for k, v in node.items() if k not in _DROP}

    for key in _MAP_KEYS:
        if isinstance(out.get(key), dict):
            out[key] = {name: _harden(sub) for name, sub in out[key].items()}
    for key in _LIST_KEYS:
        if isinstance(out.get(key), list):
            out[key] = [_harden(sub) for sub in out[key]]
    for key in _CONTAINER_KEYS:
        if key in out:
            out[key] = _harden(out[key])

    if out.get("type") == "object" or "properties" in out:
        properties = out.get("properties")
        if isinstance(properties, dict):
            out["type"] = "object"
            out["additionalProperties"] = False
            # Strict mode requires every declared property to be required. An optional field
            # must be nullable in the type instead, so the model answers "none" explicitly.
            out["required"] = list(properties)
    return out


def _unconstrained_objects(node: Any, path: str = "<root>") -> list[str]:
    """Every object in ``node`` that would validate any object at all.

    Draft 2020-12 treats a keyword it does not recognise as annotation and ignores it, so
    ``propertys`` is a legal schema and a validator that accepts everything. The question here is
    therefore not "is this spelled like a keyword" but "does this object actually constrain".

    Spelling was the other candidate and it is wrong in both directions. It refuses a legal
    tagged union, because Pydantic emits ``discriminator`` and that is not a Draft 2020-12
    keyword; it flags every property NAME, because names sit in key position under ``properties``
    and ``$defs``; and it still passes ``{"type": "object"}``, which is spelled perfectly and
    accepts every object in existence.

    What it asks for is what strict mode demands and what ``_harden`` already produces:
    ``properties``, ``additionalProperties: false``, and a ``required`` naming exactly the
    declared properties. It walks the same keys ``_harden`` walks, so it can never wander into an
    ``enum`` member, a ``const`` or a ``default``, which are data rather than schemas.

    ``"object" in types`` rather than an equality test is what accepts ``{"type": ["object",
    "null"]}``, which is how the vision schema declares an absent box and an absent place.
    """
    if isinstance(node, list):
        return [
            problem
            for index, item in enumerate(node)
            for problem in _unconstrained_objects(item, f"{path}[{index}]")
        ]
    if not isinstance(node, dict):
        return []

    problems: list[str] = []
    declared = node.get("type")
    types = declared if isinstance(declared, list) else [declared]
    if "object" in types or "properties" in node:
        properties = node.get("properties")
        if not isinstance(properties, dict) or not properties:
            problems.append(f"{path} declares no properties")
        elif node.get("additionalProperties") is not False:
            problems.append(f"{path} does not set additionalProperties to false")
        elif sorted(node.get("required") or []) != sorted(properties):
            problems.append(f"{path} does not require every property it declares")

    for key in _MAP_KEYS:
        subschemas = node.get(key)
        if isinstance(subschemas, dict):
            for name, sub in subschemas.items():
                problems.extend(_unconstrained_objects(sub, f"{path}.{key}.{name}"))
    for key in _LIST_KEYS:
        subschemas = node.get(key)
        if isinstance(subschemas, list):
            problems.extend(_unconstrained_objects(subschemas, f"{path}.{key}"))
    for key in _CONTAINER_KEYS:
        if key in node:
            problems.extend(_unconstrained_objects(node[key], f"{path}.{key}"))
    return problems


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The strict-mode JSON Schema for a Pydantic model.

    Raises ``StructuredOutputError`` if the model produces no object schema, which happens when
    a caller passes a ``RootModel`` over a scalar. Strict mode needs a top-level object.
    """
    schema = model.model_json_schema(ref_template="#/$defs/{model}")
    hardened = _harden(schema)
    if hardened.get("type") != "object":
        raise StructuredOutputError(
            f"{model.__name__} does not describe a JSON object at the top level. Strict mode "
            "needs an object; wrap the value in a model with a named field."
        )
    return hardened


def response_format_for_schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """The complete ``response_format`` value around a schema written by hand.

    Not hardened, because a hand-written strict-mode schema is written strict: the caller owns
    ``additionalProperties: false`` and a complete ``required`` at every level, and has a test
    that walks the document and says so. Hardening it here would hide the mistake that test is
    there to catch.

    The schema is checked twice before it is sent, because it is now also what the response is
    validated against locally, and legality is not enough. It has to be legal JSON Schema, and it
    has to constrain: Draft 2020-12 ignores a keyword it does not recognise, so a misspelled
    ``properties`` is a legal document and a validator that accepts everything, which is the same
    silent-no-op failure ``guided_json`` already demonstrated one layer down.

    The constraint rule governs schemas sent to a model endpoint and used to judge the reply. It
    is not exported and must not be reused for ``predicate.value_schema``, which is a different
    thing in a different module: those describe one assertion's ``object_value``, most of them
    scalars, and several would be refused by a rule written for a strict response format.
    """
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise StructuredOutputError(
            f"the schema for {name!r} is not a legal JSON Schema and would be sent to the "
            f"endpoint and used to validate the reply: {exc.message}"
        ) from exc
    vacuous = _unconstrained_objects(schema)
    if vacuous:
        raise StructuredOutputError(
            f"the schema for {name!r} carries an object that constrains nothing, so it would "
            "validate any object at all and canonical state would be written from an unchecked "
            "reply. Draft 2020-12 ignores a keyword it does not recognise, so a misspelled "
            "'properties' is a legal schema and a silently vacuous validator. Strict mode needs "
            "properties, additionalProperties false, and every property listed in required, at "
            f"every object: {'; '.join(vacuous)}"
        )
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def _is_array(schema: Mapping[str, Any], defs: Mapping[str, Any]) -> bool:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        schema = defs.get(reference.rsplit("/", 1)[-1], {})
    kind = schema.get("type")
    if kind == "array" or (isinstance(kind, list) and "array" in kind):
        return True
    return any(_is_array(choice, defs) for choice in schema.get("anyOf") or ())


def _arrays_last(schema: Any, defs: Mapping[str, Any]) -> Any:
    """``schema`` with each object's array properties listed after its other properties."""
    if isinstance(schema, list):
        return [_arrays_last(item, defs) for item in schema]
    if not isinstance(schema, Mapping):
        return schema
    out = {key: _arrays_last(value, defs) for key, value in schema.items()}
    properties = out.get("properties")
    if isinstance(properties, Mapping):
        names = list(properties)
        ordered = [n for n in names if not _is_array(properties[n], defs)]
        ordered += [n for n in names if _is_array(properties[n], defs)]
        out["properties"] = {name: properties[name] for name in ordered}
        if isinstance(out.get("required"), list):
            out["required"] = [name for name in ordered if name in out["required"]]
    return out


def response_format_for(
    model: type[BaseModel], *, name: str | None = None, arrays_last: bool = False
) -> dict[str, Any]:
    """The complete ``response_format`` value. The only one the client will send.

    ``arrays_last`` lists each object's array properties after its other properties in the schema
    sent, and so in the order the model writes them; the model class and every other use of its
    schema are untouched. Key order changes nothing a reply is validated for. It is a decoding
    concern: under a strict schema a field written after an array needs a comma there, and a
    model that wrote a line break in its place was measured writing whitespace to the token limit,
    since the schema then admits only the comma or whitespace. An array listed last can be followed
    only by its object's closing brace. Off by default; a caller whose form has such an array turns
    it on.
    """
    schema = strict_json_schema(model)
    if arrays_last:
        schema = _arrays_last(schema, schema.get("$defs") or {})
    return response_format_for_schema(schema, name or model.__name__)


def _json_array_spans(content: str) -> list[tuple[int, int]]:
    """Every balanced ``[...]`` in ``content`` that parses as a JSON array, as ``(start, end)``.

    A region that balances but does not parse is prose that happened to contain a bracket, and
    is not a span, exactly as it is not a candidate for braces. ``the sign reads [OPEN which
    never closes properly]`` is text.
    """
    spans: list[tuple[int, int]] = []
    index = content.find("[")
    while index != -1:
        end = _balanced_end(content, index, opening="[", closing="]")
        if end is not None:
            try:
                parsed = json.loads(content[index:end])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                spans.append((index, end))
                index = content.find("[", end)
                continue
        index = content.find("[", index + 1)
    return spans


def _object_spans(content: str) -> list[tuple[int, dict[str, Any]]]:
    """Every balanced ``{...}`` in ``content`` that parses, with the offset it starts at."""
    found: list[tuple[int, dict[str, Any]]] = []
    index = content.find("{")
    while index != -1:
        end = _balanced_end(content, index)
        if end is not None:
            try:
                parsed = json.loads(content[index:end])
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                found.append((index, parsed))
                index = content.find("{", end)
                continue
        index = content.find("{", index + 1)
    return found


def json_object_candidates(content: str) -> list[dict[str, Any]]:
    """Every **top-level** balanced ``{...}`` in ``content`` that parses as a JSON object.

    The scan is deliberately not a regex and not a naive brace counter: brace counting that
    ignores quoting mis-parses any JSON string containing a brace, and transcribed signage will
    eventually contain one.

    Three rules keep the count honest.

    *   A region that balances **and** parses is one candidate, and the scan resumes after its
        closing brace. Objects nested inside an answer are part of that answer, not rivals to it.
    *   A region that balances but does not parse is prose that happened to contain braces, so
        the scan resumes one character in rather than skipping the region. ``the sign read
        {OPEN} until {"a": 1}`` must not lose the object that follows the noise.
    *   An object inside a JSON array is **not** top level and is not a candidate. This word was
        in the sentence above before it was in the code: the scan started at the first ``{``
        wherever it sat, so ``[{"a": 1}]`` yielded ``{"a": 1}`` and a reply that was an array was
        read as an object. Nothing in the body says which element of an array is the answer, and
        taking the first is the same guess this scanner was rewritten to stop making.
    """
    arrays = _json_array_spans(content)
    return [
        parsed
        for start, parsed in _object_spans(content)
        if not any(begin < start < end for begin, end in arrays)
    ]


def extract_json_object(content: str) -> dict[str, Any]:
    """The one JSON object in a body that may also carry untagged reasoning text.

    Raises ``StructuredOutputError`` when there is no object at all, because prose is a failed
    call rather than a partial success. There is no lenient path: a half-parsed object is a fact
    with a piece missing rather than a smaller fact.

    Raises ``AmbiguousStructuredOutputError`` when the body carries two or more **different**
    objects. That is the scratch-work case: the model drafted an example object while thinking
    and then wrote its real one, both inline in ``message.content`` with nothing delimiting
    them. Neither position is evidence of which is the answer, so the call is refused. Identical
    candidates are not ambiguous and collapse to one, because every reading of the body yields
    the same value.

    Raises ``SchemaViolationError`` when the whole body parses as a single JSON document that is
    not an object. That reply is not an answer wrapped in scratch work: it parsed cleanly and was
    the wrong type, so there is nothing inside it to extract. The bodies the scan exists for are
    unaffected, because neither prose in front of an object nor a fenced object parses as one
    document.
    """
    try:
        whole = json.loads(content)
    except json.JSONDecodeError:
        pass
    else:
        if not isinstance(whole, dict):
            raise SchemaViolationError(
                "the whole response body parses as JSON and is a top-level "
                f"{'array' if isinstance(whole, list) else 'scalar'} rather than an object. "
                "Nothing is taken from inside it: the reply parsed cleanly and was simply not "
                "the requested type, so unwrapping it would hand the caller a value the endpoint "
                "never said was the answer. Strict mode needs a top-level object. Body was "
                f"{content[:300]!r}",
                errors=("<root>: the reply is not of type 'object'",),
            )

    candidates = json_object_candidates(content)
    if not candidates and _object_spans(content) and _json_array_spans(content):
        raise SchemaViolationError(
            "the response body carries objects, and every one of them is an element of a JSON "
            "array. An array element is not the answer: the reply at that point was an array, "
            "and nothing in the body says which element to take. Strict mode needs a top-level "
            f"object. Body was {content[:300]!r}",
            errors=("<root>: the reply is not of type 'object'",),
        )
    if not candidates:
        raise StructuredOutputError(
            "the response body contained no parseable JSON object. Naked prose never enters "
            "canonical state, so this call is a failure rather than a partial success. Body was "
            f"{content[:300]!r}"
        )

    distinct: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        fingerprint = json.dumps(candidate, sort_keys=True, ensure_ascii=False)
        if fingerprint not in seen:
            seen.add(fingerprint)
            distinct.append(candidate)

    if len(distinct) == 1:
        return distinct[0]

    summary = " | ".join(
        json.dumps(candidate, sort_keys=True, ensure_ascii=False)[:300] for candidate in distinct
    )
    raise AmbiguousStructuredOutputError(
        f"the response body contained {len(distinct)} different JSON objects and nothing in it "
        "says which one is the answer. The reasoning models write scratch work inline in the "
        "content with no delimiter, and a draft object in that scratch work is schema-valid, so "
        "guessing at position would persist a placeholder as a real assertion. This call is "
        f"refused rather than guessed at. Candidates were {summary}",
        candidates=tuple(distinct),
    )


def validate_against_schema(
    payload: Any, schema: Mapping[str, Any], *, name: str = "response"
) -> dict[str, Any]:
    """Validate a parsed payload against the exact schema that was sent, or raise.

    Sending ``response_format {type: json_schema, strict: true}`` asks the endpoint to enforce a
    shape. It does not prove the endpoint did. `runtime-verification.md` section 6 measured the
    neighbouring parameter, ``guided_json``, being accepted and silently ignored on this very
    platform, and a server that ignores ``json_schema`` the same way answers HTTP 200 with a
    perfectly well-formed object of the wrong shape. Without this function that object is
    returned to the caller as a result.

    Raises ``SchemaViolationError``, which is a ``StructuredOutputError``, so a caller that
    already catches the family is unaffected.
    """
    validator = Draft202012Validator(dict(schema))
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.absolute_path))
    if not errors:
        if not isinstance(payload, dict):
            raise SchemaViolationError(
                f"the {name} schema validated a {type(payload).__name__} rather than an object. "
                "Strict mode needs a top-level object."
            )
        return payload

    detail = tuple(
        f"{'/'.join(str(part) for part in err.absolute_path) or '<root>'}: {err.message}"
        for err in errors[:8]
    )
    raise SchemaViolationError(
        f"the reply does not satisfy the {name!r} schema that this request sent, in "
        f"{len(errors)} place(s). response_format was json_schema strict, so either the "
        "endpoint ignored it or the schema and the prompt disagree. Either way the payload is "
        f"not written to canonical state. Violations: {'; '.join(detail)}",
        errors=detail,
    )


def _balanced_end(
    content: str, start: int, *, opening: str = "{", closing: str = "}"
) -> int | None:
    """Index just past the bracket closing the one at ``start``, or None if unbalanced.

    Quote aware, because brace counting that ignores quoting mis-parses any JSON string
    containing a brace and transcribed signage will eventually contain one. The same is true of
    a square bracket, which is why the pair is a parameter rather than two copies of this.
    """
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index + 1
    return None
