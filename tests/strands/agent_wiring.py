"""Everything the agent depends on except the model, checked without spending anything.

    python tests/strands/agent_wiring.py

WHY THIS IS A SEPARATE HARNESS. A review needs a live model: credentials, a network call and a bill.
Everything underneath it does not, and that "everything" is where the mistakes actually live -- a
server that fails to launch, a tool that is not advertised, a knowledge article the agent cannot
reach, a path that escapes containment. Isolating the model means all of that is verifiable on every
run rather than on the runs someone is willing to pay for.

It launches the real `anchor` binary over stdio, which is the wiring an MCP host uses, and asks it
the questions the agent will ask.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from agent import anchor_server, find_cli  # noqa: E402
from agent.policy_agent import BEDROCK_TOKEN_ENV  # noqa: E402

# The tools a review cannot proceed without, and the articles the system prompt sends the agent to.
REQUIRED_TOOLS = {"CheckPolicy", "DescribePolicyModule", "ListKnowledge", "ReadKnowledge"}
REQUIRED_ARTICLES = {"reading-verdicts", "event-schemas-and-pins", "the-modelled-subset",
                     "writing-a-property-module", "smoke-vs-exhaustive", "what-anchor-does-not-check"}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def check_bedrock_isolation() -> None:
    """That authenticating by API key does not read `~/.aws`, and that this is why no native
    dependency is needed.

    NO CREDENTIALS AND NO NETWORK. Clients are constructed and one request is signed and then
    aborted at `before-send`, so nothing leaves the machine and no quota is touched. The bearer
    token here is a dummy; a real one would prove nothing extra, since it is never validated.

    What this pins down is a decision that is invisible at runtime and silently reversible: botocore
    resolves the credential chain before consulting the bearer token and then discards it, so a
    chain that raises kills the client over a value nothing uses. `keyed_session` stops the chain
    being walked. If someone "simplifies" that away, a machine whose default profile uses
    `login_session` goes back to failing with `pip install botocore[crt]`.
    """
    import boto3
    from agent.policy_agent import isolate_from_shared_config, keyed_session

    # The decision table. A key means the machine's config is irrelevant; naming a profile is an
    # explicit request for it; no key means ordinary credentials are genuinely needed.
    check("a key and no profile isolates from ~/.aws",
          isolate_from_shared_config("some-key", None) is True)
    check("a named profile reads ~/.aws",
          isolate_from_shared_config("some-key", "work") is False)
    check("no key reads ~/.aws",
          isolate_from_shared_config(None, None) is False)

    # No profile means no profile region, so one has to be given. Silence here would mean picking
    # up whichever region the SDK defaults to, which decides WHICH MODELS EXIST.
    try:
        keyed_session(boto3, None)
        check("a missing region is refused, not defaulted", False, "no SystemExit")
    except SystemExit as e:
        check("a missing region is refused, not defaulted", "region" in str(e).lower())

    # A stray AWS_PROFILE is set deliberately, because it must NOT leak in: an empty config has no
    # profiles, so an inherited name would raise ProfileNotFound inside a session built to need none.
    with environment(AWS_PROFILE="no-such-profile-for-testing",
                     **{BEDROCK_TOKEN_ENV: "wiring-test-not-a-real-token"}):
        try:
            client = keyed_session(boto3, "us-east-1").client("bedrock-runtime")
        except Exception as e:  # noqa: BLE001 -- failing to construct IS the finding
            # What a machine with a `login_session` default profile gets if the isolation is ever
            # removed. Note the message names botocore[crt], not the configuration that reached it.
            check("a client builds without reading ~/.aws, and AWS_PROFILE does not leak", False,
                  f"{type(e).__name__}: {str(e).splitlines()[0][:110]}")
            return

        check("a client builds without reading ~/.aws, and AWS_PROFILE does not leak", True)

        # THE ONE THAT MATTERS. None means the chain was never walked -- which is the whole reason
        # botocore[crt] is not a dependency.
        check("the credential chain is not walked",
              client._request_signer._credentials is None,
              repr(client._request_signer._credentials))

        # And the request is still authenticated, by the token rather than by SigV4.
        signed = {}

        def before_send(request, **kwargs):
            signed["auth"] = request.headers.get("Authorization")
            raise _Abort()

        client.meta.events.register("before-send.bedrock-runtime.*", before_send)
        try:
            client.converse(modelId="amazon.nova-lite-v1:0",
                            messages=[{"role": "user", "content": [{"text": "x"}]}])
        except Exception:
            pass
        auth = signed.get("auth")
        auth = auth.decode() if isinstance(auth, bytes) else auth
        scheme = auth.split(" ", 1)[0] if auth else None
        check("the request is signed with the bearer token", scheme == "Bearer", repr(scheme))


def check_refusals() -> None:
    """That a far-side refusal is reported as an outcome, not as a traceback.

    A QUOTA ERROR IS NOT A CRASH -- it means every layer worked and the account said no at the end.
    The distinction is easy to lose in a refactor, and losing it makes a working setup look broken.
    """
    from agent.policy_agent import refused

    import io, contextlib

    def report(message: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = refused(RuntimeError(message))
        return code, err.getvalue()

    code, text = report("An error occurred (ThrottlingException) ...: Too many tokens per day")
    check("a spent daily quota is explained, not dumped",
          code == 2 and "DAILY TOKEN BUDGET" in text and "Traceback" not in text, text[:80])

    code, text = report("ValidationException: This model doesn't support tool use in streaming mode")
    check("a model that refuses streamed tools points at --no-stream",
          code == 2 and "--no-stream" in text, text[:80])

    # An unrecognised failure must NOT be dressed up as something understood.
    code, text = report("something nobody has seen before")
    check("an unknown failure is passed through plainly",
          code == 1 and "something nobody has seen before" in text, text[:80])


@contextmanager
def environment(**values: str):
    """Set environment variables for the block and put the originals back afterwards.

    A test that leaves `AWS_PROFILE` or a bearer token behind would change what every LATER check in
    this process sees, so the restore matters more than it looks.
    """
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, was in previous.items():
            if was is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = was


class _Abort(Exception):
    """Stops a signed request before any network I/O."""


def main() -> int:
    print(f"anchor CLI: {find_cli()}\n")

    client = anchor_server()
    with client:
        # --- the tools a review needs ------------------------------------------------------------
        tools = client.list_tools_sync()
        names = {t.tool_name for t in tools}
        print(f"tools advertised: {', '.join(sorted(names))}\n")
        for tool in sorted(REQUIRED_TOOLS):
            check(f"tool `{tool}` is advertised", tool in names)

        # --- the knowledge base, both ways it is offered -----------------------------------------
        listed = client.call_tool_sync("wiring-list", "ListKnowledge", {})
        listed_text = str(listed)
        for article in sorted(REQUIRED_ARTICLES):
            check(f"article `{article}` is listed", article in listed_text)

        resources = client.list_resources_sync()
        uris = {str(r.uri) for r in resources.resources}
        check("articles are also served as MCP resources",
              all(f"anchor://knowledge/{a}" in uris for a in REQUIRED_ARTICLES),
              f"saw {sorted(uris)}")

        # The one the system prompt leans on hardest: it is what stops a bounded verdict being
        # reported as a proof.
        verdicts = client.read_resource_sync("anchor://knowledge/reading-verdicts")
        verdicts_text = str(verdicts)
        for phrase in ("VACUOUS", "bound", "callerPrincipal"):
            check(f"reading-verdicts carries `{phrase}`", phrase.lower() in verdicts_text.lower())

        # --- a real check, so the whole tool path is exercised ------------------------------------
        result = client.call_tool_sync("wiring-check", "CheckPolicy",
                                       {"policy": "tests/policies/dead_forbid.dw"})
        text = str(result)
        check("CheckPolicy reports the DEAD forbid", "DEAD" in text)
        check("CheckPolicy carries the reading caveat", "DOGWOOD'S OWN DEFAULT" in text.upper())

        # --- containment, which exists for exactly this caller ------------------------------------
        escaped = str(client.call_tool_sync("wiring-escape", "CheckPolicy",
                                            {"policy": "../../CLAUDE.md"}))
        check("a path escaping the project is refused",
              "outside this project" in escaped or "error" in escaped.lower(),
              escaped[:120])

        # --- a refusal is not a pass ---------------------------------------------------------------
        refused = str(client.call_tool_sync("wiring-refuse", "CheckPolicy",
                                            {"policy": "tests/policies/like_impossible.dw"}))
        check("a policy outside the subset is REFUSED, not empty", "REFUSED" in refused)

        # --- Bedrock credential isolation, which costs nothing to check --------------------------
        check_bedrock_isolation()
        check_refusals()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1

    print("the agent's MCP wiring is sound; only the model call is untested here.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
