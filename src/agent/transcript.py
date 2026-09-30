"""Render a Strands conversation as markdown: the prose, and every tool call underneath it.

A review's final paragraph is the part a person reads. It is also the part that cannot be
checked -- it is the model's words, and the whole question about this agent is whether those words
are warranted by what the tools actually returned. A transcript is what makes that answerable.

SO THE TOOL CALLS ARE THE POINT, not decoration around the answer. `CheckPolicy` with its exact
arguments, and the checker's reply in full, is the evidence; the paragraph above it is a claim
about that evidence. Anyone can then read the two side by side and disagree.

No model is needed to render one, so this is tested like everything else that does not need one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

# A tool result can be the checker's entire output -- hundreds of lines per rule under --verbose.
# Kept generous, because the reason to save a transcript is to be able to check the answer against
# the evidence, and evidence trimmed to a snippet is a summary of a summary.
RESULT_LIMIT = 6000


def render_value(value: Any) -> str:
    """Tool input as JSON, on one line when it is short enough to read that way."""
    try:
        compact = json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)
    if len(compact) <= 100:
        return compact
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def result_text(result: dict) -> str:
    """Everything a tool returned, flattened to text."""
    parts = []
    for block in result.get("content", []) or []:
        if "text" in block:
            parts.append(str(block["text"]))
        elif "json" in block:
            parts.append(json.dumps(block["json"], indent=2, default=str))
        else:
            # A shape this renderer does not model -- named rather than dropped, because a
            # transcript missing part of what a tool returned is a transcript that misleads.
            parts.append(f"<{', '.join(block)}>")
    return "\n".join(parts)


def render(messages: list[dict], *, question: str = "", heading: str = "",
           meta: dict | None = None, limit: int = RESULT_LIMIT, tools: bool = True) -> str:
    """One exchange as markdown. `messages` is the agent's own message list after a run.

    `tools=False` for an agent that has none -- the pipeline's reviewer and reporter answer from
    what they are given, by design -- so the absence of tool calls is not flagged as a finding."""
    lines: list[str] = []
    if heading:
        lines += [f"## {heading}", ""]
    if question:
        lines += ["**Asked:**", "", "> " + "\n> ".join(question.strip().splitlines()), ""]
    if meta:
        lines += ["| | |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in meta.items()]
        lines.append("")

    calls = 0
    for message in messages:
        role = message.get("role", "?")
        for block in message.get("content", []) or []:
            if "text" in block:
                text = str(block["text"]).strip()
                # The user turn is the question, already quoted above.
                if text and role != "user":
                    lines += [text, ""]

            elif "toolUse" in block:
                calls += 1
                use = block["toolUse"]
                lines += [f"**Tool call {calls}** — `{use.get('name', '?')}`", "",
                          "```json", render_value(use.get("input")), "```", ""]

            elif "toolResult" in block:
                body = result_text(block["toolResult"])
                status = block["toolResult"].get("status", "")
                clipped = len(body) > limit
                lines += [f"<details><summary>tool result{f' ({status})' if status else ''}"
                          f"{' — clipped' if clipped else ''}</summary>", "",
                          "```", body[:limit] + ("\n…" if clipped else ""), "```", "",
                          "</details>", ""]

    if not calls and tools:
        # Worth saying out loud: an answer with no tool calls is the model talking about a policy
        # it never looked at, which reads exactly like one it checked.
        lines += ["> **No tools were called for this answer.**", ""]

    return "\n".join(lines).rstrip() + "\n"


def header(title: str, subtitle: str = "",
           by: str = "src/agent/policy_agent.py --transcript") -> str:
    """The top of a transcript file, stamped so it can be told from a later run."""
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# {title}", ""]
    if subtitle:
        lines += [subtitle, ""]
    lines += [f"*Generated {when} by `{by}`. Tool calls and "
              "their full replies are included: the prose is a claim, and the tool output is the "
              "evidence for it.*", ""]
    return "\n".join(lines)
