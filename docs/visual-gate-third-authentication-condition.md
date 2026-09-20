# Should the visual gate accept a third way of proving who a page is?

Status: **NAMED CONDITION `preview-shell-credentialed-tiles`**.
`AUTHENTICATION_CONDITIONS` in `exulanica/evaluation/gate_keys.py` lists it.
`authenticationConditionOf` in `scripts/capture_visual_gate.mjs` assigns it from one run's traffic.
This page is the case that proposed the rule. An operator decision admitted it. This scoring lane
does not own later widening of the list.

A lane that would benefit from a gate being widened must not be the lane that widens it. The lane
stated the rule and held; the list grew by an operator decision, not by this lane.

## The three named conditions

The gate drives the real product through a real street, walks 125 metres of it, and takes the three
photographs it scores. It records how a page proved who it was before it scores what that page drew.
The closed list names three ways. A page that matches none of them is refused rather than guessed.
That refusal is the gate working, not a fault.

The three it names:

- **`credentialed-api`**, the product shell, which talks only to the real API and never to
  development routes;
- **`vite-preview-api`**, the development preview, which talks only to development routes and never
  to the real API;
- **`preview-shell-credentialed-tiles`**, a development preview that reads its street from the real
  API, with a credential.

This page is the third. It is not a hybrid by accident: a street lives in the store, and only the
real API serves it.

## The named rule

`authenticationConditionOf` names a run `preview-shell-credentialed-tiles` when **all five** of
these are true of it:

1. the page made at least one `/preview-api/` request, so it is the preview and not the product
   shell;
2. every `/api/` response served 200 was under `/api/tiles`, so nothing else was served to it;
3. it asked `/api/graph` and was not served it, so the credential does not carry the graph;
4. an anonymous read of the API is refused;
5. at least one tile was actually served.

The first four are the approved clauses. The fifth is a narrowing in the harness: without it, clause
2 is true of a page served nothing, so a condition named for credentialed tiles could be satisfied
by a run that received none. Every run that passes five also passes the four.

## The evidence, measured on the run

    the page asks for the graph          403 Forbidden
    the page asks for the street tiles   200, five times
    a caller with no credential asks     401 Unauthorized

**The pair is the point, and it is stronger evidence than an absence would have been.** A page that
simply never asked for anything else would prove nothing about what it was allowed to have. This
page asks and is turned away, while an anonymous caller is turned away differently. That means the
API distinguishes *no credential* from *a credential that does not carry this*, and the page holds
the second kind.

I first drafted clause 3 as "the page never asks for anything else", then looked at what the page
does. It does ask. Written from the draft, the condition would never have matched the page it was
written for.

## Why the two existing ways cannot simply be stretched

- **The product shell condition** requires that the page used no development routes at all. That
  requirement is what makes the condition mean "this is the shipped product". This page used six.
- **The development preview condition** requires that the page never touched the real API at all.
  That requirement is what makes it mean "nothing here came from the real system".

The second one matters beyond today. **An earlier judged run is retained under it.** Loosening it now
would quietly change what that retained record asserts about a run nobody can ever repeat. A record
whose meaning can be edited afterwards is not a record.

## The weak point in the named rule, stated rather than buried

Clause 3 depends on the page **happening** to ask for something it is refused. Nothing requires it to
keep doing that. If the page changes and stops asking, the underlying fact stays true while the
evidence for it disappears, and runs would then stop for a reason that looks nothing like the cause.

It fails in the safe direction: the gate refuses rather than accepts. The durable repair is for the
gate to do the asking itself, with the page's credential, instead of waiting for the page to do it
out of habit. That is a further credential question, not something this lane can settle.

## What refusing the condition would have cost

The operator admitted the condition, so a matching run can be scored. The costs below are the
rejected alternative of leaving the list at two names. Three other routes existed and only one of
them is real:

- **Serve the street through the development routes instead of the real API.** The page would then
  satisfy the existing preview condition unchanged. This is a change to the application and the API,
  not to the gate. **This lane has not verified that such a route exists or could.**
- **Commit the street as a file, the way the test fixture is committed.** **Measured, and it cannot
  work**: the walk needs 131 metres of ground and one tile is 128 metres across, and the extra ground
  comes from neighbouring tiles that are fetched from the store listing. A committed file is a single
  tile, so it cannot hold this walk at all.
- **Score it through the product shell rather than the preview.** **Unverified by this lane**, and a
  different target with its own condition.

If the list had stayed at two names, the gate could walk this street and never score it, and the
project's stop condition would stay out of reach on this page.

## What the named condition admits, stated at its widest

A named condition should be read against the widest thing that fits through it, not against the one
case in front of you.

The rule admits **any** development preview page, for any world, any location, and any
number of tiles, so long as the real API served it nothing but street tiles, refused it the graph,
and refuses anonymous callers. It is not limited to this street, this run, or this lane.

**And it constrains what a page DID, not what its credential is ALLOWED to do.** A credential with
far more authority than the page happens to exercise would pass this condition unchanged, because the
gate can only observe the requests that were made. If what matters to you is the authority granted
rather than the authority used, this rule does not give you that, and no rule written from observed
traffic can.

**That is the honest general statement, and here is the bound on it, which is narrower and in this
rule's favour.** The condition is judged for each run separately, out of that run's own traffic, and
clause 2 requires that everything the API actually served was a tile. So a page holding a wider
credential passes ONLY IF IT DID NOT USE IT, and a run that did use it fails clause 2 and cannot be
scored at all. The gap is therefore not "a powerful credential is admitted". Precisely:

> **The rule certifies that a run was clean. It cannot certify that the credential was narrow.**

For a gate whose job is to state how a scored page got its content, run-cleanliness is the property
that matters and is the property this rule delivers. The gap can be closed entirely from outside the
gate, by issuing the harness a credential that carries tiles and nothing else, at which point used
authority and granted authority are the same thing and the distinction stops existing. That is a
credential action rather than a gate rule, and it is not this lane's to take.

## What is already decided, and by whom

- The gate refusing to score a page whose condition it cannot name: existing behaviour, working.
- The rule's shape and its evidence: proposed by this lane, reviewed and approved in shape by the
  orchestrator, then admitted onto the closed list as `preview-shell-credentialed-tiles`.
- Whether a credentialed page may be scored under that named condition: decided; the harness
  assigns the name from the run's traffic.
