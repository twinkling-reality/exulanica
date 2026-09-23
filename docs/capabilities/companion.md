# Companion

The Companion is your AI partner within the world: someone to explore and create with, who helps
you understand what happens and continue shared activities. This is the intended experience; the
implementation boundaries are described below.

## Product role

The Companion provides company and creation assistance within the world. Conversation, awareness of the current activity,
and continuity across shared experiences support that role. Its purpose includes participating
in the experience, beyond retrieving places or answering questions.

## Design requirements

A recognizable personality, awareness of what the person is doing, and shared history should
shape its responses. These are design requirements for the intended experience, not claims of
implemented capabilities. Appearance, initiative, and the boundaries of shared-history retention
need concrete interaction design. Familiarity does not authorize edits or identity decisions.

## Implementation

Conversation, selection, and reviewed appearance proposal machinery exist. Persistent shared
history and participation in world activities require further implementation and evaluation.
Creation assistance must use supported, reviewable editing operations; arbitrary creation commands
and simulation control depend on the editing and runtime contracts.

See [interaction design](../interaction-model.md),
[frontend integration](../atlas-frontend-integration.md), and
[grounded question contract](../companion-question.md).
