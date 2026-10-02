"""The AgentCore reading: Dogwood under AgentCore's event schema, plus AgentCore's own rules.

AgentCore runs Dogwood with an event schema of its own (`agentcore.dwschema`, transcribed from the
AgentCore guide and corroborated against the engine -- docs/agentcore.md). Under it the scope
fields are `eventPrincipal` / `eventResource` and history is partitioned by session. That much is
an ordinary event schema, and `parse_schema` reads it like any other.

What it does NOT cover is the layer AgentCore adds at policy creation, which Dogwood's validator
knows nothing about. Two kinds of thing live here:

  REJECTIONS  rules AgentCore enforces when a policy is created, so a policy breaking one cannot be
              deployed and a verdict about it would be about nothing. Reported as such -- not as
              REFUSED, which means the construct is outside what Anchor models.
  REFUSALS    constructs whose meaning under AgentCore Anchor cannot pin down with a one-gateway
              model, refused under this reading only.

Each rule cites where AWS states it.
"""

from __future__ import annotations

import re
from pathlib import Path

from .parse import Unsupported

AGENTCORE_SCHEMA = Path(__file__).resolve().parent / "agentcore.dwschema"

# AgentCore's names for the scope fields. A policy binding either is written for AgentCore.
AGENTCORE_FIELDS = re.compile(r"\b(eventResource|eventPrincipal)\s*:")

# "Temporal operators per policy: 3" (policy-temporal.md, Quotas). Which constructs count is not
# stated: Dogwood's guide says there are exactly three operators, `formerly`, `previous`, `since`,
# while the AgentCore page lists `count` and `sum` among them too. The narrow count is certain to
# be at least what AgentCore counts; the broad one is the most it could count.
OPERATOR_LIMIT = 3
OPERATORS = ("formerly", "previous", "since")
AGGREGATES = ("count", "sum")


def uses_agentcore_fields(text: str) -> bool:
    """Does the policy text bind AgentCore's scope fields? Comments are not policy."""
    return bool(AGENTCORE_FIELDS.search(re.sub(r"//[^\n]*", "", text)))


def is_agentcore(schema: dict) -> bool:
    """Is this AgentCore's event schema -- the one whose scope fields are AgentCore's?"""
    return "eventResource" in schema.get("scope_fields", {})


def _walk(node):
    """Every dict in a parsed policy condition, each once.

    Once by IDENTITY: a `formerly` term holds its predicate as both `atom` and `left`, so walking
    by structure meets it twice -- and reported each missing bind twice.
    """
    stack, seen = [node], set()
    while stack:
        n = stack.pop()
        if id(n) in seen:
            continue
        seen.add(id(n))
        if isinstance(n, dict):
            yield n
            stack.extend(n.values())
        elif isinstance(n, list):
            stack.extend(n)


def _label(i: int, policy: dict) -> str:
    action = ", ".join(policy["actions"]) or "any action"
    return f"{policy['effect']} #{i} ({action})"


def rejections(policies: list[dict]) -> tuple[list[str], list[str]]:
    """What AgentCore would refuse to create, and what it might.

    `(rejections, warnings)`. Run on policies parsed under AgentCore's schema, so the
    `eventResource` bind has already become the internal `callerResource` one.
    """
    rejected, warned = [], []
    for i, p in enumerate(policies, 1):
        nodes = list(_walk(p["cond"]))

        # "Every predicate must include eventResource: resource ... Omitting it is rejected with
        # `temporal predicates do not constrain the matched event to the current request's
        # resource`" (example-policies-temporal.md, Before you use these examples). Not a Dogwood
        # rule: the engine validates such a policy, and only AgentCore refuses it.
        for n in nodes:
            if {"action", "kind", "binds"} <= n.keys():
                if not any(b.get("side") == "scope" and b.get("field") == "callerResource"
                           and b.get("kind") == "scope" and b.get("name") == "resource"
                           for b in n["binds"]):
                    rejected.append(
                        f"{_label(i, p)}: the predicate on {n['action']}::{n['kind']} has no "
                        f"`eventResource: resource`, which AgentCore requires in every temporal "
                        f"predicate (\"temporal predicates do not constrain the matched event to "
                        f"the current request's resource\")")

        narrow = sum(1 for n in nodes if n.get("op") in OPERATORS and "window" in n)
        broad = narrow + sum(1 for n in nodes if n.get("kind") in AGGREGATES and "binders" in n)
        if narrow > OPERATOR_LIMIT:
            rejected.append(f"{_label(i, p)}: {narrow} temporal operators "
                            f"(`formerly`/`previous`/`since`), over AgentCore's limit of "
                            f"{OPERATOR_LIMIT} per policy")
        elif broad > OPERATOR_LIMIT:
            warned.append(f"{_label(i, p)}: {broad} temporal operators if `count` and `sum` count "
                          f"as operators, as the AgentCore guide lists them; AgentCore allows "
                          f"{OPERATOR_LIMIT}, and does not say whether they do")
    return rejected, warned


def refuse_unsound(policies: list[dict]) -> None:
    """Refuse the two forms a one-gateway model cannot answer for under AgentCore.

    The model has one gateway. That is exact for `formerly`, the aggregates and a negated-left
    `since`, because the mandatory `eventResource: resource` means a predicate can only match an
    event at the deciding request's own gateway. It is NOT exact for these two, because AgentCore
    partitions history by SESSION and a session can span gateways (docs/agentcore.md, question 3):

      - a positive-left `since` must hold at every position of the session's history since its
        anchor, and another gateway's event is such a position where it fails;
      - `previous` reads the session's immediately preceding event, which may be another gateway's.

    The one-gateway answer would be right for a single-gateway deployment and wrong otherwise, with
    nothing in the verdict saying which. AgentCore's guide documents neither form.
    """
    for i, p in enumerate(policies, 1):
        for n in _walk(p["cond"]):
            if n.get("op") == "previous" and "window" in n:
                raise Unsupported(
                    f"{_label(i, p)} uses `previous`, whose meaning under AgentCore depends on "
                    f"other gateways' events in the same session, which a one-gateway model "
                    f"cannot see", "under AgentCore: previous, or a positive-left since")
            if n.get("op") == "since" and "window" in n and not n.get("leftNeg"):
                left = n.get("left") or {}
                if left.get("op") != "not":
                    raise Unsupported(
                        f"{_label(i, p)} uses `since` with a positive left operand, which must "
                        f"hold at every event of the session since its anchor, other gateways' "
                        f"included -- a one-gateway model cannot see them",
                        "under AgentCore: previous, or a positive-left since")
