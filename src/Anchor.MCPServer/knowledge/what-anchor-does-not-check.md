---
title: What Anchor does not check
description: The limits to state alongside any verdict, so a bounded answer is not reported as a proof.
---

# What Anchor does not check

Every answer here is worth exactly what its assumptions are worth. State these alongside a verdict
rather than letting a reader infer more than was established.

## It is bounded model checking, not proof

The state space is explored up to `attempts` session length and a small value domain per field. So
every **negative** answer — `VACUOUS`, `REDUNDANT`, `DEAD`, `no difference` — is of the form *no
session within this bound*. Not *never*.

A **positive** answer is stronger: a witness was exhibited, so it exists.

Nothing here is proved unboundedly. That would need an inductive invariant and a proof assistant;
this is TLC, and TLC checks a model.

## It does not check that the policy is correct

The three built-in findings are *derivable* — statable without knowing intent. They would all pass a
firewall policy that let the whole internet in. "Every rule is live" is not "the policy is
right". For intent you must state it yourself: see `writing-a-property-module`.

## It does not replace the gateway's validator

Anchor models a subset (see `the-modelled-subset`) and answers semantic questions. It is not a
syntax checker for the whole language, and passing here does not mean the policy deploys.

The reverse also holds and is more interesting: `dogwood validate` accepts policies that Anchor
proves **VACUOUS**. Validation and meaning are different questions.

## It assumes a deterministic decision

The model treats a decision as a deterministic function of (policy, history, request). The
reference engine can optionally register an `http_get` host function for provider scripts, which
would make evaluation depend on the network. Every claim here is scoped to the default build, where
that is not compiled in.

## It answers about the reading you gave it

Without an event schema, answers use Dogwood's own default reading, **`callerPrincipal` pinned**. A
deployment whose schema differs — no universal pin, or a pin on something else such as `sessionId`
— may decide differently. See `event-schemas-and-pins`. Leaving the reading out is the single most
common way a verdict gets over-reported.

## Under `smoke`, it answers less

A smoke run settles only `live`. See `smoke-vs-exhaustive`.

## How to report a verdict honestly

Include, in one sentence: the verdict, the bound it holds within, and the reading it was computed
under. For example —

> `permit #2` is VACUOUS within 3 attempts under Dogwood's default reading (no event schema was
> supplied, so `callerPrincipal` is pinned; a deployment with a different schema could differ). It
> grants nothing.
