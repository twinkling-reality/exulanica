# Person regions, masking and presentation consent

Design note, 2026-09-06. Not implemented. Written after the first real reconstructions showed
that the current gate ("a named human states there are no visible people or sensitive person
regions") is too coarse: the retained bowl photographs contain the arms, hands and clothing of
diners at the frame edge, no faces, and the reviewer's statement said no visible people. The
system needs an explicit list of person regions and a consent state per person, not a yes/no.

## Principles

- **Default deny.** A person region is hidden until a consent says otherwise. Absence of a
  decision is not consent.
- **Three separate consents.** Presence (this person was here), naming (this person is Julie),
  likeness (show this person's appearance). A person can be present and named while hidden.
- **Mask before, not only after.** Reconstruction reads a masked derivative of each photograph,
  so a hidden person never becomes depth, point maps or Gaussians. Viewer-side hiding exists only
  for the reversible "temporarily hidden" state of a person who has consented to likeness.
- **Bodies, not faces.** Clothing, tattoos, hands and posture identify people. A region covers the
  whole silhouette. Any face-like or body-like detection is a person until a human says otherwise.
- **No biometric templates.** Locating a region is allowed; computing or storing anything that
  could recognize the same person elsewhere is not. Names come from a person who labels, never
  from a model that matches. This keeps the existing constraint intact.
- **Receipts, not flags.** Every consent transition is an immutable receipt with actor, time and
  scope. The World Memory Package carries them, and a verifier that respects the format enforces
  the current state offline.

## States

| State | Meaning | Source derivative | Geometry | Atlas |
| --- | --- | --- | --- | --- |
| unknown | detected or confirmed, no decision | masked | excluded | silhouette, unnamed |
| present | presence consented, likeness not | masked | excluded | silhouette, name if naming consented |
| shown | likeness consented | original | included | visible |
| hidden (temporary) | likeness consented, hidden for now | original | included | silhouette at view time |
| withdrawn | consent revoked | masked; derived artifacts purged | excluded, rebuilt | absent |

"withdrawn" reuses the existing withdrawal and purge path; the others are new.

## Stages

1. **`person_regions`** (deterministic over exact source bytes and a pinned detector). Output: a
   digest-bound list of regions per photograph, each a polygon or box with a detector confidence
   and a `confirmed_by` field that is null until a human reviews. The review screen replaces the
   present free-text statement: the reviewer confirms, adds missed regions, and deletes false
   positives; every edit is a receipt. The stage records detector identity and version in its
   parameters so a detector change is a new stage version.
2. **`masked_source`** (deterministic over source bytes, confirmed regions and consent states at
   build time). Output: one derivative image per photograph with hidden regions filled by a
   neutral fill, plus a manifest naming which person each mask belongs to. Depth, pose, placement
   and training read this derivative when any region is hidden. Held-out evaluation uses the same
   derivative so scores never reward reproducing a hidden person. The derivative digest enters the
   scene build inputs, so a later consent change produces a new build rather than mutating one.
3. **Presentation rule in Atlas.** The graph payload carries, per member and per person, the
   current state and a silhouette outline in image coordinates. The inspector and the source veils
   draw the silhouette and the name when permitted; the world never draws pixels for a masked
   region. The status says how many people are hidden in the displayed scene.

## Checks that make it real

- A masked person leaves no geometry: after training, no Gaussian with meaningful opacity sits on
  rays through a masked region in any training view. Record the count in the evaluation bundle.
- Consistency across views: a person confirmed in one photograph and present in others must have
  a region in each, or the reviewer is asked; a single missed frame reconstructs the person.
- Consent UI for the subject, not only the owner: a link the person in the photograph can open to
  set their own state, with the receipt naming them as actor. Without this the layer is theater.
- Reflections and screens count as regions.

## Out of scope for the first pass

Automatic re-identification of the same person across photographs (would need embeddings), audio,
and generative fill of masked areas. Masked areas are neutral, and the status says so.

## Relationship to the current gate

The human screening receipt stays the gate. Its content changes from a statement of absence to a
confirmed region list with states. The two retained collections would be re-screened under the
new stage; the bowl would record two unnamed present people, hidden, and the volcanic set none.
