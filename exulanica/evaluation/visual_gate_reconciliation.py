"""The visual gate key reconciliation record, measured from the retained records, briefs and rubric.

It binds the rubric it fixes (checked for the version 5 wording, then by digest) and the version 4
record it replaces (checked to differ only where it may), with the calibration reply from
:mod:`~exulanica.evaluation.visual_gate_calibration`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    AUTHENTICATION_CONDITIONS,
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    CLASSIFICATION,
    EVIDENCE_KINDS,
    GATE_KEY_SET_VERSION,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    OPTION_ANSWERS,
    PICTURE_TITLES,
    REASON_FOLLOW_UP,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_PATH,
    RUBRIC_QUESTION,
    RUBRIC_V1,
    RUBRIC_VERSION,
    SUPERSEDED_VERSIONS,
    THRESHOLDS,
    TYPED_REPLY_RULE,
    VERSION_4,
    WORDS_STORAGE,
    GateKey,
    reason_follow_up,
    resolve,
)
from exulanica.evaluation.visual_gate_calibration import (
    _calibration,
    calibration_words_file,
)
from exulanica.evaluation.visual_gate_words import (
    _ISO_DATE,
    COMPOSITION,
    CORRIDOR_BAR,
    DIGEST_BOUND_PROFILE,
    JUDGE_WORDS_DIRECTORY,
    GateEvidenceError,
    _companion_binding,
    _require_name,
    _shown_texts,
    digest_bound,
    refuse_private_words,
)

#: What each retained brief required for each key it named, quoted. The reconciliation record
#: carries these, and :func:`reconciliation_record` refuses any quote the brief does not contain,
#: so a paraphrase cannot stand in for the criterion a run was actually held to.
BRIEFED_CRITERIA: Final[Mapping[str, Mapping[str, str]]] = {
    "helsinki-visual-feasibility": {
        "continuousTexturedStreetAndFacades": (
            "Continuous source-textured ground along the initial route."
        ),
        "readsAsInhabitedStreet": "A recognizable Helsinki urban street at the pilot.",
        "noCutsOrFloatingGeometry": "No floating or cut geometry visible on the initial route.",
        "usefulEyeLevelMovement": (
            "Correct eye-level first-person movement on simplified verified support."
        ),
        "companionPresent": "Existing Companion and reticle remain present.",
        "reticlePresent": "Existing Companion and reticle remain present.",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "Existing authored-object and authentication handlers are not replaced."
        ),
    },
    "helsinki-terminal-lod-successor": {
        "continuousTexturedStreetAndFacades": (
            "continuous source-textured street along the initial route;"
        ),
        "readsAsInhabitedStreet": "a recognizable Helsinki urban scene;",
        "noCutsOrFloatingGeometry": "no cut, floating or camera-occluding geometry;",
        "usefulEyeLevelMovement": (
            "movement only over stable terminal support with full capsule clearance;"
        ),
        "completeCapsuleClearanceVerification": (
            "A vertical capsule of radius 0.34 metres and total height 1.9 metres, grounded "
            "on that support, intersects no visual triangle except the support surface."
        ),
        "companionPresent": "Companion and reticle present;",
        "reticlePresent": "Companion and reticle present;",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "authenticated shell and authored handlers preserved."
        ),
    },
    "melbourne-c4-29-visual-feasibility": {
        "continuousTexturedStreetAndFacades": (
            "continuous source-textured street and facades along the complete route;"
        ),
        "readsAsInhabitedStreet": "a recognizable Melbourne urban scene;",
        "noCutsOrFloatingGeometry": (
            "no large cuts, floating geometry, or camera-occluding surfaces;"
        ),
        "usefulEyeLevelMovement": "useful eye-level movement over verified route support;",
        "completeCapsuleClearanceVerification": (
            "a vertical capsule of radius 0.34 metres and total height 1.9 metres, grounded on "
            "that support, has full clearance from visual geometry except the support surface;"
        ),
        "practicalBrowserBudget": (
            "practical measured browser transfer, decoded-memory, draw-call and frame budgets."
        ),
        "companionPresent": "Companion and reticle present;",
        "reticlePresent": "Companion and reticle present;",
        "authenticatedShellAndAuthoredHandlersPreserved": (
            "authenticated shell and authored handlers preserved;"
        ),
    },
}

#: Where a retained criterion differs in substance from the canonical definition, said once.
_SCOPE_NOTES: Final[Mapping[str, str]] = {
    "continuousTexturedStreetAndFacades": (
        "All three briefs required SOURCE texture, and the first two named only the ground or the "
        "street. The canonical key drops the source condition, because a generated corridor has "
        "no source texture and a key naming one could not be scored against it, and it widens the "
        "surface to street and facades. It is also mechanised: the retained values were judged "
        "from captures."
    ),
    "readsAsInhabitedStreet": (
        "Renamed and redefined by the operator's binding. The retained keys asked whether a real, "
        "named city was recognisable, were scored before the rubric existed, and are not rubric "
        "scores. Rubric version 4 asks one plain question of each capture, whether it is a "
        "finished, lived-in street, with options that say what they mean, and stops at the first "
        "no."
    ),
    "noCutsOrFloatingGeometry": (
        "The retained criteria were judged from captures, Melbourne's only for LARGE cuts, and "
        "the successor briefs also named camera-occluding surfaces, which the canonical set "
        "measures under completeCapsuleClearanceVerification. The canonical key is measured over "
        "all drawn geometry."
    ),
    "usefulEyeLevelMovement": (
        "The first Helsinki brief asked for correct movement on simplified verified support, the "
        "successor folded full capsule clearance into this key, and Melbourne asked for useful "
        "movement over verified support while its recorder retained only a static camera segment. "
        "The canonical key requires a live numeric trace and keeps capsule clearance separate."
    ),
    "completeCapsuleClearanceVerification": (
        "Scored as its own key only by Melbourne. The successor brief required the same capsule "
        "inside its movement criterion and its record carries no separate key for it, so it is "
        "absent there, as it is in the first Helsinki record, whose brief never named a capsule."
    ),
    "practicalBrowserBudget": (
        "Melbourne's brief named frame budgets among the practical budgets. The canonical key "
        "reports frame time and heap beside Melbourne's but decides only on the values that do "
        "not vary between runs of one build."
    ),
    "companionPresent": "Presence of the product's Companion, now read from the live document.",
    "reticlePresent": "Presence of the product's reticle, now read from the live document.",
    "authenticatedShellAndAuthoredHandlersPreserved": (
        "The first Helsinki brief required authored-object and authentication handlers to remain, "
        "and its record says handler preservation was verified structurally, but its hardPass "
        "block has no key for it, so it is absent there and no value is inferred. Version 3 "
        "names pointer listeners beside keyboard listeners, because the product enters its world "
        "with a click."
    ),
}

#: Lines the rubric must carry, verbatim, for the reconciliation record to bind it.
_RUBRIC_LINES: Final = (
    f"Rubric version: {RUBRIC_VERSION}\n",
    f"Key set: `{GATE_KEY_SET_VERSION}`",
    RUBRIC_QUESTION,
    RUBRIC_GUIDANCE,
    ANSWER_REQUIREMENT,
    CARRIED_WORDS_NOTICE,
    WORDS_STORAGE,
    TYPED_REPLY_RULE,
    *(reason_follow_up(answer) for answer in OPTION_ANSWERS.values()),
    *(f"**{option}**" for option in ANSWER_OPTIONS),
    f"`{NOT_ASKED}`",
    "**No model may score `readsAsInhabitedStreet`.**",
    *(f"| `{label}` | {title} |" for label, title in PICTURE_TITLES.items()),
)

#: What version 4 said a corridor has to clear, before the bar said the yes answers are picked.
_V4_CORRIDOR_BAR: Final = (
    "all three pictures answered yes by the named judge, plus every mechanical key, against a "
    "baseline that does not itself hold every key"
)

#: Every refusal the record writer makes, as the records state them.
_WRITER_REFUSES: Final = (
    "a missing or placeholder judge",
    "a missing reason in the judge's own words, including a follow-up that gets no words",
    "a reply that does not say when it was given",
    "a rubric digest mismatch, except a judgement given against the version this one superseded "
    "when that version showed the judge exactly what this one shows",
    "a capture not bound by digest, or an answer about another capture",
    "a yes key with any picture unasked",
    "an answer given after a decisive no",
    "a typed reply that does not hold the whole word no, or that holds the whole word yes",
    "a follow-up for an answer that already gave its reason, or one not in the rubric's words",
    "a pick that is not one of the options",
    "carried words without the line that says they are kept, or from a rubric version that was "
    "never fixed",
    "a yes whose only words are carried words, and a follow-up for a picture whose earlier words "
    "are carried",
    "any answer or follow-up reply not typed by the judge",
    "a public record that would carry any of the judge's words, or a quoted part of them",
)


def _normalised(text: str) -> str:
    return " ".join(text.split())


def _brief_quote_holds(quote: str, brief_text: str) -> bool:
    folded = _normalised(brief_text)
    # Line-wrapped list items keep their leading numerals inside the brief; a quote omits them.
    return _normalised(quote) in folded


def _rubric_binding(rubric: bytes, copy_path: str) -> dict[str, Any]:
    """The rubric the record fixes: checked for the version 5 wording, then bound by digest."""
    text = rubric.decode("utf-8")
    for line in _RUBRIC_LINES:
        if line not in text:
            raise GateEvidenceError(f"FINDING: the rubric does not carry {line.strip()!r}")
    earlier = {
        *(question for _, question in RUBRIC_V1.questions),
        *(version.question for version in SUPERSEDED_VERSIONS),
    } - {RUBRIC_QUESTION}
    for question in sorted(earlier):
        if question in text:
            raise GateEvidenceError(f"FINDING: the rubric still asks {question!r}")
    judges = re.findall(r"^Named human judge: (.*)$", text, flags=re.MULTILINE)
    if len(judges) != 1:
        raise GateEvidenceError("FINDING: the rubric must name exactly one judge")
    judge = _require_name(judges[0].strip(), "a judge named in the rubric")
    return {
        "path": copy_path,
        "byte_size": len(rubric),
        "sha256": hashlib.sha256(rubric).hexdigest(),
        "copyOf": RUBRIC_PATH,
        "rubricVersion": RUBRIC_VERSION,
        "judge": judge,
    }


def _superseded_binding(document: Mapping[str, Any], path: str) -> dict[str, Any]:
    """The version 4 record, checked to say what version 4 said and to differ only where it may."""
    if document.get("profile") != DIGEST_BOUND_PROFILE:
        raise GateEvidenceError(f"{path} is not a digest-bound record")
    body = document["record"]
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if digest != document["record_sha256"]:
        raise GateEvidenceError(f"FINDING: {path} does not reproduce its record_sha256")
    judged = body["judgedKey"]
    stated = (
        body["keySet"],
        judged["rubricVersion"],
        judged["rubricSha256"],
        judged["question"],
        judged["guidance"],
        judged["requirement"],
        judged["reasonFollowUp"],
        judged["carriedWordsNotice"],
        judged["options"],
        judged["composition"],
        judged["corridorBar"],
        judged["wordsStorage"],
        judged.get("typedReplyRule"),
    )
    expected = (
        VERSION_4.key_set,
        VERSION_4.rubric_version,
        VERSION_4.rubric_sha256,
        VERSION_4.question,
        VERSION_4.guidance,
        VERSION_4.requirement,
        REASON_FOLLOW_UP,
        VERSION_4.carried_notice,
        list(VERSION_4.options),
        VERSION_4.composition,
        _V4_CORRIDOR_BAR,
        WORDS_STORAGE,
        None,
    )
    if stated != expected:
        raise GateEvidenceError(f"FINDING: {path} is not the version 4 record this supersedes")
    if not VERSION_4.shows_what_is_shown_now():
        raise GateEvidenceError(
            "FINDING: version 5 may change only how a typed reply is read, and it changes what "
            "the judge is shown"
        )
    changed: dict[str, dict[str, str]] = {}
    unchanged: list[str] = []
    for entry, item in zip(body["canonicalKeys"], CANONICAL_KEYS, strict=True):
        current = _canonical_entry(item)
        if entry["key"] != item.spelling:
            raise GateEvidenceError(f"FINDING: {path} orders the canonical keys differently")
        before = VERSION_4.definitions.get(item.spelling, item.definition)
        if entry["definition"] != before:
            raise GateEvidenceError(f"FINDING: {path} defines {item.spelling} unexpectedly")
        if {**entry, "definition": current["definition"]} != current:
            raise GateEvidenceError(
                f"FINDING: {item.spelling} changed more than its wording since {path}; version 5 "
                "moves no measurement"
            )
        if before == item.definition:
            unchanged.append(item.spelling)
        else:
            changed[item.spelling] = {"before": before, "after": item.definition}
    for name, value in (
        ("thresholds", dict(THRESHOLDS)),
        ("melbourneEnvelope", dict(MELBOURNE_ENVELOPE)),
        ("classification", dict(CLASSIFICATION)),
        ("authenticationConditions", list(AUTHENTICATION_CONDITIONS)),
    ):
        if body[name] != value:
            raise GateEvidenceError(f"FINDING: {name} moved since {path}; version 5 moves none")
    return {
        "path": path,
        "record_sha256": digest,
        "keySet": VERSION_4.key_set,
        "rubricVersion": VERSION_4.rubric_version,
        "rubricSha256": VERSION_4.rubric_sha256,
        "changes": {
            "typedReplyRule": {"before": VERSION_4.typed_reply_rule, "after": TYPED_REPLY_RULE},
            "composition": {"before": VERSION_4.composition, "after": COMPOSITION},
            "corridorBar": {"before": _V4_CORRIDOR_BAR, "after": CORRIDOR_BAR},
            "writerRefuses": {"before": judged["writerRefuses"], "after": list(_WRITER_REFUSES)},
            "definitions": changed,
        },
        "shownUnchanged": True,
        "keysWithUnchangedDefinitions": unchanged,
        "measurementsUnchanged": True,
        "keyValuesChanged": [],
        "unchanged": [
            "every spelling, definition and resolution",
            "every measurement, threshold and mechanical decision, so no key value changes",
            "everything the judge is shown: the picture titles, the question, the guidance, the "
            "line asking for words, the two options, the carried-words line and the one follow-up",
            "that the answer is the option the judge picks",
            "that each picture is shown alone, the first no decides, and the key holds only for "
            "three yes answers",
            "that there is no score",
            "the named judge",
            "that no model may answer, suggest, pre-fill or break a tie",
            "that the judge's own words are kept exactly as typed in a private companion record, "
            "never in a public one, and are the reason; and that an answer without a reason is not "
            "recorded",
            "that the rubric SHA-256 is bound",
            "that captures are bound by path, byte size and SHA-256",
        ],
        "why": {
            "typedReplyRule": (
                "Under version 4 a typed reply counted only when its first word was yes or no, so "
                "a reply that says no without opening with it could not be read. Version 5 reads "
                "a typed reply as no when it holds the whole word no and not the whole word yes, "
                "and never as yes. A typed reply can therefore only fail a key, never pass one. "
                "That is the cautious direction for a stop condition, so the rule cannot inflate "
                "a result."
            ),
            "corridorBar": (
                "The bar stays absolute: three picked yes answers from the named judge, plus every "
                "mechanical key. It now says picked, because a typed reply can never be a yes."
            ),
        },
        "adoption": (
            "This rule was adopted after the version 4 reply described under calibrationEvidence "
            "was given, and that reply is the rule's first application. The judge had declined "
            "further questions about these pictures, so none was asked again."
        ),
        "knownCost": (
            "The whole word no inside a favourable sentence would read as a no. That can only "
            "ever fail a key, never pass one. Every ask therefore presents the two options, so "
            "that a reply typed in place of a pick stays rare."
        ),
        "notReRead": (
            "The replies given under version 2, kept as calibration evidence by the version 3 "
            "reconciliation record, are not re-read. They were given under version 2, which asked "
            "a different question. One of them, typed in place of a pick, holds the whole word no "
            "and not the whole word yes, so this rule would read it as a no; the rule is not "
            "applied to them, and nothing is taken from them."
        ),
        "answersAcceptedFromVersion4": (
            "A judgement given against version 4 is read under version 5, because version 4 "
            "showed the judge exactly what version 5 shows. A record written from one carries "
            "both digests and labels the judge's reasons with version 4. A judgement given "
            "against any other version is refused."
        ),
        "strictness": (
            "Version 4 could read a typed reply as a yes; version 5 reads one only as a no, and "
            "the key still needs three picked yes answers, so version 5 is at least as strict as "
            "version 4."
        ),
    }


def reconciliation_record(
    *,
    date: str,
    base: str,
    branch: str,
    retained: Mapping[str, Mapping[str, Any]],
    briefs: Mapping[str, bytes],
    superseded: Mapping[str, Any],
    superseded_path: str,
    rubric: bytes,
    rubric_copy_path: str,
    calibration: Mapping[str, Any],
    calibration_captures: Sequence[Mapping[str, Any]],
    scored_corridors: Sequence[str],
    scored_against_superseded: Sequence[str],
    record_path: str,
) -> dict[str, Any]:
    """The key reconciliation record, measured from the retained records, briefs and rubric.

    ``retained`` maps each retained label to its parsed document and ``briefs`` maps it to the
    bytes of its brief. ``superseded`` is the version 4 reconciliation record this one replaces,
    ``rubric`` the bytes of the rubric it fixes, retained at ``rubric_copy_path``, and
    ``calibration`` the reply typed under version 4 about ``calibration_captures``, whose
    words go only to the private companion named by ``record_path``.
    ``scored_corridors`` are the retained records that score a corridor and
    ``scored_against_superseded`` those scored against an earlier key set; both must be empty,
    because a rubric may change only before anything is read against it. Every fact is re-derived
    from those inputs and compared with :data:`exulanica.evaluation.gate_keys.RETAINED_RECORDS`;
    any disagreement is a finding and raises rather than being written.
    """
    if not _ISO_DATE.match(date):
        raise GateEvidenceError("date must be an ISO date")
    if scored_corridors:
        raise GateEvidenceError(
            "FINDING: a corridor has been scored "
            f"({', '.join(scored_corridors)}), so the rubric cannot be revised by this record"
        )
    if scored_against_superseded:
        raise GateEvidenceError(
            "FINDING: records were scored against an earlier key set "
            f"({', '.join(scored_against_superseded)}); they need their own reconciliation"
        )
    labels = [record.label for record in RETAINED_RECORDS]
    if set(retained) != set(labels) or set(briefs) != set(labels):
        raise GateEvidenceError(f"the three retained records and briefs are required: {labels}")

    supersedes = _superseded_binding(superseded, superseded_path)
    rubric_entry = _rubric_binding(rubric, rubric_copy_path)
    if rubric_entry["sha256"] in {version.rubric_sha256 for version in SUPERSEDED_VERSIONS}:
        raise GateEvidenceError("FINDING: the rubric is a superseded version's; nothing is revised")
    evidence, private_replies, private_lines = _calibration(
        calibration, calibration_captures, rubric_entry["judge"]
    )
    companion_path, companion = calibration_words_file(
        record_path, calibration, calibration_captures, rubric_entry["judge"]
    )
    predecessor_records: list[dict[str, str]] = [
        {"path": superseded_path, "record_sha256": supersedes["record_sha256"]}
    ]
    retained_entries: list[dict[str, Any]] = []
    spelling_uses: dict[str, list[str]] = {}
    artifacts: list[dict[str, Any]] = []
    melbourne_preview: dict[str, Any] | None = None

    for expected in RETAINED_RECORDS:
        document = retained[expected.label]
        if document.get("profile") != DIGEST_BOUND_PROFILE:
            raise GateEvidenceError(f"{expected.path} is not a digest-bound record")
        body = document["record"]
        digest = hashlib.sha256(canonical_json(body)).hexdigest()
        if digest != document["record_sha256"] or digest != expected.record_sha256:
            raise GateEvidenceError(
                f"FINDING: {expected.path} canonicalises to {digest}, declares "
                f"{document['record_sha256']} and was reconciled at {expected.record_sha256}"
            )
        hard_pass = body["hardPass"]
        actual = {resolve(spelling): spelling for spelling in hard_pass}
        if len(actual) != len(hard_pass):
            raise GateEvidenceError(
                f"FINDING: two spellings in {expected.path} resolve to one canonical key"
            )
        if actual != dict(expected.spellings):
            raise GateEvidenceError(
                f"FINDING: {expected.path} scored {sorted(hard_pass)}, which is not the spelling "
                "set this module reconciled"
            )
        brief_bytes = briefs[expected.label]
        brief_text = brief_bytes.decode("utf-8")
        brief_binding = next(
            (item for item in body["artifacts"] if item["path"] == expected.brief_path), None
        )
        brief_digest = hashlib.sha256(brief_bytes).hexdigest()
        if (
            brief_binding is None
            or brief_binding["sha256"] != brief_digest
            or brief_binding["byte_size"] != len(brief_bytes)
        ):
            raise GateEvidenceError(
                f"FINDING: {expected.brief_path} is not the brief {expected.path} binds"
            )
        artifacts.append(
            {"path": expected.brief_path, "byte_size": len(brief_bytes), "sha256": brief_digest}
        )
        criteria = BRIEFED_CRITERIA[expected.label]
        for quote in criteria.values():
            if not _brief_quote_holds(quote, brief_text):
                raise GateEvidenceError(
                    f"FINDING: {expected.brief_path} does not contain the quoted criterion "
                    f"{quote!r}"
                )
        keys: dict[str, Any] = {}
        for item in CANONICAL_KEYS:
            spelling = actual.get(item.spelling)
            entry: dict[str, Any]
            if spelling is None:
                entry = {"state": "absent", "note": "not scored in this record's hardPass block"}
            else:
                value = hard_pass[spelling]
                if not isinstance(value, bool):
                    raise GateEvidenceError(f"FINDING: {expected.path} {spelling} is not a boolean")
                entry = {"state": "scored", "spelling": spelling, "retainedValue": value}
                spelling_uses.setdefault(spelling, []).append(expected.label)
            if item.spelling in criteria:
                entry["briefedCriterion"] = criteria[item.spelling]
            keys[item.spelling] = entry
        predecessor_records.append({"path": expected.path, "record_sha256": digest})
        retained_entries.append(
            {
                "label": expected.label,
                "path": expected.path,
                "record_sha256": digest,
                "brief": expected.brief_path,
                "verdict": body["verdict"],
                "browserEngine": body["browser"]["engine"],
                "viewport": body["browser"]["viewport"],
                "hardPassKeyCount": len(hard_pass),
                "keys": keys,
            }
        )
        if expected.label == "melbourne-c4-29-visual-feasibility":
            browser = body["browser"]
            melbourne_preview = {
                "key": "authenticatedShellAndAuthoredHandlersPreserved",
                "retainedValue": hard_pass["authenticatedShellAndAuthoredHandlersPreserved"],
                "authenticatedShellPresent": browser["authenticatedShellPresent"],
                "previewApi404s": [
                    {"url": item["url"], "status": item["status"]}
                    for item in browser["previewApi404s"]
                ],
                "statement": (
                    "Melbourne set authenticatedShellAndAuthoredHandlersPreserved to true while "
                    "its browser block recorded these three 404 responses from the Vite-only "
                    "preview API, not from a credentialed backend. As the retained evidence used "
                    "it, the key means the product shell and its authored handlers were present "
                    "and were not replaced by a bespoke harness page; it does not by itself "
                    "assert a real bearer token. Every canonical record therefore carries "
                    "authenticationCondition: vite-preview-api is Melbourne's condition, and "
                    "credentialed-api, a real token against a real API, is strictly stronger."
                ),
            }
    artifacts.append({key: rubric_entry[key] for key in ("path", "byte_size", "sha256")})

    if melbourne_preview is None:  # pragma: no cover - labels are checked above
        raise GateEvidenceError("the Melbourne record was not read")
    if len(melbourne_preview["previewApi404s"]) != 3:
        raise GateEvidenceError("FINDING: Melbourne does not record exactly three preview 404s")

    mapping: list[dict[str, Any]] = []
    for item in CANONICAL_KEYS:
        for spelling in (item.spelling, *item.predecessor_spellings):
            mapping.append(
                {
                    "spelling": spelling,
                    "resolvesTo": resolve(spelling),
                    "usedBy": sorted(spelling_uses.get(spelling, [])),
                    "isCanonicalSpelling": spelling == item.spelling,
                }
            )
    if mapping != superseded["record"]["mapping"]:
        raise GateEvidenceError("FINDING: the spelling table moved, and version 5 does not move it")
    used = set(spelling_uses)
    listed = {entry["spelling"] for entry in mapping}
    if not used <= listed:
        raise GateEvidenceError(f"FINDING: unmapped retained spellings {sorted(used - listed)}")
    resolved_targets: dict[str, set[str]] = {}
    for entry in mapping:
        resolved_targets.setdefault(entry["spelling"], set()).add(entry["resolvesTo"])
    ambiguous = sorted(name for name, targets in resolved_targets.items() if len(targets) > 1)
    if ambiguous:
        raise GateEvidenceError(f"FINDING: ambiguous spellings {ambiguous}")

    canonical_entries = [_canonical_entry(item) for item in CANONICAL_KEYS]
    for spelling in CANONICAL_SPELLINGS:
        if "Source" in spelling or "Melbourne" in spelling:
            raise GateEvidenceError(f"{spelling} names a source or a city")

    record: dict[str, Any] = {
        "profile": "exulanica.visual-gate-key-reconciliation/v5",
        "date": date,
        "status": "reconciled",
        "base": base,
        "branch": branch,
        "keySet": GATE_KEY_SET_VERSION,
        "rubricVersion": RUBRIC_VERSION,
        "supersedes": supersedes,
        "predecessor_records": predecessor_records,
        "artifacts": artifacts,
        "captures": [dict(capture) for capture in calibration_captures],
        "canonicalKeys": canonical_entries,
        "evidenceKinds": list(EVIDENCE_KINDS),
        "judgedKey": {
            "key": JUDGED_KEY,
            "rubric": RUBRIC_PATH,
            "rubricVersion": RUBRIC_VERSION,
            "rubricSha256": rubric_entry["sha256"],
            "rubricCopy": rubric_entry["path"],
            "judge": rubric_entry["judge"],
            "captures": list(CAPTURE_LABELS),
            "pictures": [
                {"label": label, "title": title} for label, title in PICTURE_TITLES.items()
            ],
            "question": RUBRIC_QUESTION,
            "guidance": RUBRIC_GUIDANCE,
            "requirement": ANSWER_REQUIREMENT,
            "reasonFollowUp": REASON_FOLLOW_UP,
            "carriedWordsNotice": CARRIED_WORDS_NOTICE,
            "options": list(ANSWER_OPTIONS),
            "optionAnswers": dict(OPTION_ANSWERS),
            "wordsStorage": WORDS_STORAGE,
            "judgeWordsDirectory": JUDGE_WORDS_DIRECTORY,
            "typedReplyRule": TYPED_REPLY_RULE,
            "answersAcceptedAgainst": [
                {"rubricVersion": RUBRIC_VERSION, "rubricSha256": rubric_entry["sha256"]},
                {
                    "rubricVersion": VERSION_4.rubric_version,
                    "rubricSha256": VERSION_4.rubric_sha256,
                },
            ],
            "notAsked": NOT_ASKED,
            "composition": COMPOSITION,
            "corridorBar": CORRIDOR_BAR,
            "scoredBy": (
                "the human judge named in the rubric, never a model: no model may answer, "
                "suggest, pre-fill or break a tie"
            ),
            "writerRefuses": list(_WRITER_REFUSES),
        },
        "calibrationEvidence": evidence,
        "judgeWords": _companion_binding(companion_path, companion),
        "thresholds": dict(THRESHOLDS),
        "melbourneEnvelope": dict(MELBOURNE_ENVELOPE),
        "classification": dict(CLASSIFICATION),
        "authenticationConditions": list(AUTHENTICATION_CONDITIONS),
        "retainedRecords": retained_entries,
        "mapping": mapping,
        "mappingChecks": {
            "retainedSpellings": len(used),
            "retainedSpellingsResolved": len(used & listed),
            "total": used <= listed,
            "unambiguous": not ambiguous,
            "canonicalKeys": len(CANONICAL_KEYS),
        },
        "scoredBeforeRevision": {
            "corridors": list(scored_corridors),
            "againstEarlierKeySets": list(scored_against_superseded),
            "measuredAs": (
                "retained records under docs/evaluation whose file name or record profile names "
                "a corridor, and those whose gate block names key set version 1, 2, 3 or 4, read "
                "when this record was written"
            ),
        },
        "authenticatedShellUnderMelbourne": melbourne_preview,
        "scopeNotes": dict(_SCOPE_NOTES),
        "claimsNotMade": [
            "No canonical value is asserted for any retained run. Retained values are quoted "
            "under the spelling each record used, and the retained records are not edited.",
            "No key absent from a retained record is inferred true or false.",
            "No generated geometry is scored here, and none existed in this repository when the "
            "rubric was revised.",
            "The canonical definitions do not make any retained rejection pass or fail anew.",
            "The version 4 record is superseded, not edited. No corridor was scored, and no "
            "record was written, under versions 1, 2, 3 or 4, and no answer was scored under "
            "version 4.",
            "The version 4 reply is calibration evidence here, and this record takes no key value "
            "from it. Its words are not in this record: it carries their SHA-256 and byte count, "
            "and its private companion holds them.",
            "The replies given under version 2 are not re-read under version 5, because they were "
            "given under version 2.",
            "The typed-reply rule is not presented as fixed before any answer: it was adopted "
            "after the version 4 reply was given, and that reply is its first application.",
            "Nothing here is an answer under version 5. The rubric fixes how the judge is asked "
            "and how a typed reply is read; only the named judge answers, and no model judged any "
            "picture.",
        ],
    }
    shown = [
        *_shown_texts(),
        *(f"{VERSION_4.carried_notice}\n\n{VERSION_4.prompt(label)}" for label in CAPTURE_LABELS),
    ]
    refuse_private_words(
        record,
        [item["words"] for item in private_replies if item["words"] is not None],
        shown=shown,
        lines=[item["words"] for item in private_lines],
    )
    return digest_bound(record)


def _canonical_entry(item: GateKey) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "key": item.spelling,
        "definition": item.definition,
        "evidenceKind": item.evidence_kind,
        "predecessorSpellings": list(item.predecessor_spellings),
    }
    if item.evidence_kind == "mechanical":
        entry["measurement"] = item.measurement
        entry["decidedBy"] = list(item.decided_by)
    else:
        entry["rubric"] = RUBRIC_PATH
    return entry
