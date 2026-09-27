"""An agent that reviews authorization policies, and reports what was actually established.

    python src/agent/policy_agent.py tests/policies/dead_forbid.dw
    python src/agent/policy_agent.py a.dw --against b.dw

WHAT IT IS FOR. Everything else in this repository answers a question precisely and narrowly: is
this rule load-bearing, within this bound, under this reading of history. None of that is useful to
a person unless the answer reaches them with its qualifications attached. The agent is the part that
talks to the person, and its job is not to be persuasive -- it is to not overstate.

THE SYSTEM PROMPT IS DELIBERATELY THIN, AND THAT IS THE EXPERIMENT.

`Anchor.MCPServer` ships six knowledge articles saying what each verdict does and does not mean: that
VACUOUS is bounded by `attempts` rather than absolute, that a REFUSAL is not a clean result, that
`unknown` from a smoke run is never grounds for deleting a rule, that without an event schema every
answer assumes a reading which is not the deployed one. Those articles were written for a model to
read, and until this file existed no model had ever read one.

So the prompt below does not restate them. It says the knowledge base exists and must be consulted
before a verdict is reported. Restating the caveats here would guarantee a well-qualified answer
while proving nothing about whether the knowledge base works -- and the knowledge base is what an
agent we did not write would have to rely on.

If a review comes back missing the bound or the reading, that is a finding about the articles or
the tool descriptions, not a reason to thicken this prompt.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SYSTEM_PROMPT = """\
You review authorization policies for someone who has to act on your answer.

Your tools model-check a Dogwood (.dw) policy: they report, rule by rule, whether each one is
load-bearing. They also expose a knowledge base describing what those answers do and do not
establish.

BEFORE YOU REPORT ANY VERDICT, read the knowledge-base article covering it. The tools answer
bounded questions; the articles say what the bounds are. A verdict repeated without them claims
more than was checked.

Report what was established and nothing more. If the checker declined to answer, say so and say
why -- that is not a clean result. If you are unsure whether something was established, say that
too; an honest gap is worth more here than a confident summary.
"""


def find_cli() -> Path:
    """The built Anchor CLI this agent launches as its MCP server.

    Release before Debug, since a Release tree is the deliberate one. `ANCHOR_CLI` overrides both,
    which is how a container points at wherever it installed the binary.
    """
    if (override := os.environ.get("ANCHOR_CLI")):
        return Path(override)

    for configuration in ("Release", "Debug"):
        candidate = REPO / "src" / "Anchor.CLI" / "bin" / configuration / "net10.0" / "Anchor.CLI.dll"
        if candidate.exists():
            return candidate

    raise SystemExit(
        "the anchor CLI is not built. Run:\n"
        "    dotnet build Anchor.sln\n"
        "or set ANCHOR_CLI to the path of Anchor.CLI.dll")


def anchor_server(project_dir: Path | None = None):
    """An MCP client speaking to `anchor server` over stdio.

    Launched as a child process, which is the wiring an MCP host uses and therefore the wiring worth
    exercising. `--project-dir` is passed so that every path the agent names is resolved inside the
    tree and one escaping it is refused -- the agent is exactly the caller that containment exists
    for.
    """
    from mcp import StdioServerParameters, stdio_client
    from mcp.client.stdio import get_default_environment
    from strands.tools.mcp import MCPClient

    root = str(project_dir or REPO)
    cli = find_cli()

    # A framework-dependent build is a .dll that `dotnet` runs; a self-contained publish -- what the
    # container carries, because it needs no .NET runtime installed -- is a native executable that
    # runs itself. Told apart by the suffix rather than configured, since getting it wrong produces
    # "cannot execute binary file" rather than anything about the build.
    command, prefix = ("dotnet", [str(cli)]) if cli.suffix == ".dll" else (str(cli), [])

    # `stdio_client` does NOT inherit our environment. It passes a scrubbed allow-list -- PATH, HOME,
    # TEMP and a few others -- which is a good default: it stops a server we launch from reading the
    # API key we hold. It also drops ANCHOR_ROOT, which is the one variable the server needs to find
    # the tree when there is no `Anchor.sln` to walk up to.
    #
    # In a checkout the fallback covers it and nothing looks wrong. In the CONTAINER there is no
    # solution file, so every tool call came back "No Anchor tree found" -- through the agent, which
    # reported honestly that it could not review anything. Extending the allow-list by exactly one
    # entry keeps the property the default was protecting.
    env = get_default_environment()
    if (anchor_root := os.environ.get("ANCHOR_ROOT")):
        env["ANCHOR_ROOT"] = anchor_root

    params = StdioServerParameters(
        command=command,
        args=[*prefix, "server", "--project-dir", root],
        cwd=root,
        env=env)

    return MCPClient(lambda: stdio_client(params))


GEMINI_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# The same setting name Polson uses, so one convention covers both. Colon-delimited, which is the
# .NET configuration spelling for nesting: {"ApiKeys": {"GoogleAgentPlatform": "..."}}.
GEMINI_SETTING = "ApiKeys:GoogleAgentPlatform"


def appsettings_path() -> Path | None:
    """The development settings file, if there is one.

    `ANCHOR_APPSETTINGS` first, so a container can point at a file it wrote from a secret store;
    then beside this module, which is where a developer puts it; then the repository root.

    Every one of these is gitignored by `**/*appsettings.json`. That is checked rather than assumed,
    because the whole point of the file is that it holds a key.
    """
    if (override := os.environ.get("ANCHOR_APPSETTINGS")):
        return Path(override) if Path(override).exists() else None

    for candidate in (Path(__file__).resolve().parent / "appsettings.json",
                      REPO / "appsettings.json"):
        if candidate.exists():
            return candidate
    return None


def use_appsettings(path: Path) -> None:
    """Point every later `setting()` at this file. What `--config` does.

    Sets ANCHOR_APPSETTINGS rather than a module global, because that variable already IS the
    answer to "which file holds the key" -- it is how the container image names one a secret store
    wrote -- and a flag that set something else would make two answers to one question. Every read
    is lazy and happens in this module, so doing it before the graph is built reaches all of them.

    RAISES where the environment variable falls through. An absent ANCHOR_APPSETTINGS path means
    "carry on and look in the usual places", which is right for something the environment set on
    your behalf; somebody who typed `--config` named a file, and running without a key and blaming
    the environment is the failure that would follow from ignoring it.
    """
    if not path.is_file():
        # Exit 2, the same code every other "could not run, and here is why" takes. A bare
        # SystemExit(str) prints the message and exits 1, which a script reads as a verdict.
        print(f"no settings file at {path}", file=sys.stderr)
        raise SystemExit(2)
    os.environ["ANCHOR_APPSETTINGS"] = str(path.resolve())


def setting(name: str) -> str | None:
    """One colon-delimited setting, or None. Never raises on a bad file, and never logs a value."""
    path = appsettings_path()
    if path is None:
        return None

    try:
        # utf-8-sig: a file written by a Windows editor routinely carries a BOM, and json.loads
        # rejects one.
        import json
        node = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        # The path and the failure, never the contents: this file exists to hold a secret, so a
        # parse error must not print it back out in a diagnostic.
        print(f"warning: could not read {path}: {type(e).__name__}", file=sys.stderr)
        return None

    for part in name.split(":"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]

    return node if isinstance(node, str) and node.strip() else None


def setting_raw(name: str):
    """A setting of any type. `setting` is the string-only form and is what most callers want."""
    path = appsettings_path()
    if path is None:
        return None

    try:
        import json
        node = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None

    for part in name.split(":"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def gemini_client_args() -> dict:
    """Arguments for the underlying `genai.Client`.

    A key alone reaches the public Developer API at `generativelanguage.googleapis.com`. An Agent
    Platform key does not work there -- it comes back 403 `API_KEY_SERVICE_BLOCKED`, which names the
    API rather than the mistake -- and needs `enterprise=True` with a project and location instead.
    Which one you have is a property of the key, not something worth guessing, so it is configured.

    Environment before file, as everywhere else here: a deployment injects, a developer edits.
    """
    args: dict = {}

    if (key := gemini_api_key()):
        args["api_key"] = key

    # The names google-genai reads itself, so a container that already sets them needs nothing else.
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or setting("Google:Project")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION") or setting("Google:Location")

    if project:
        args["project"] = project
    if location:
        args["location"] = location

    enterprise = os.environ.get("GOOGLE_GENAI_ENTERPRISE") or setting_raw("Google:Enterprise")
    if enterprise in (True, "true", "True", "1"):
        args["enterprise"] = True

    return args


# Bedrock takes an API key as a BEARER TOKEN in the environment rather than as a constructor
# argument: botocore builds the variable name from the service's signing name, so `bedrock` gives
# `AWS_BEARER_TOKEN_BEDROCK`. Confirmed against the installed botocore rather than assumed.
BEDROCK_TOKEN_ENV = "AWS_BEARER_TOKEN_BEDROCK"

BEDROCK_SETTING = "ApiKeys:AmazonBedrock"


def bedrock_api_key() -> str | None:
    """The Bedrock API key, from the environment or from appsettings.json. Environment first."""
    return os.environ.get(BEDROCK_TOKEN_ENV) or setting(BEDROCK_SETTING)


def isolate_from_shared_config(key: str | None, profile: str | None) -> bool:
    """Whether to build the client without reading `~/.aws` at all.

    AN API KEY MEANS THE MACHINE'S AWS CONFIG IS IRRELEVANT, and reading it anyway is what breaks.
    `Session.create_client` resolves the credential chain BEFORE consulting the bearer token and
    then discards the result, because bearer auth supersedes SigV4 at signing time. So the chain is
    walked for nothing -- and a chain that RAISES takes the client down over a value that was never
    going to be used. That is the whole of the `botocore[crt]` failure: a `[default]` profile
    carrying `login_session`, with nothing answering earlier, reaches a CRT-backed provider.

    Skipping the chain therefore changes no behaviour, it only removes a failure mode. Which is why
    it is the default when a key is configured rather than something to opt into.

    A named profile wins, because naming one is an explicit request to use it. `Bedrock:UseAwsConfig`
    forces the question either way.
    """
    if (configured := setting_raw("Bedrock:UseAwsConfig")) is not None:
        return configured in (False, "false", "False", "0", 0)
    return bool(key) and not profile


def keyed_session(boto3, region: str | None):
    """A boto3 session that cannot see `~/.aws`, for key-only authentication.

    Scoped rather than global: pointing `AWS_CONFIG_FILE` at nowhere would work identically but
    would change credential resolution for everything else in the process, and this agent spawns
    children. `os.devnull` is used rather than a made-up path because it is guaranteed to exist, to
    be empty, and to parse as a config file with no profiles in it on every platform.

    NO PROFILE MEANS NO PROFILE REGION, so a region must be given -- `Bedrock:Region`, or
    `AWS_REGION`. That is the same bargain the Google provider makes: authenticate by key, and state
    the things the key does not carry.
    """
    import botocore.session

    if not region:
        raise SystemExit(
            'Bedrock needs a region. With an API key the machine\'s AWS config is not read, so the '
            'region cannot come from a profile -- set "Bedrock": {"Region": "us-east-1"} in '
            "appsettings.json, or AWS_REGION in the environment.")

    # `session_vars` remaps (config key, env var, default, converter) per setting, and is the
    # supported way to do this. `set_config_variable` is NOT enough: it stores an instance override,
    # and an override of None reads as "unset" and falls straight through to the environment again.
    #
    # AWS_PROFILE has to go with the config files rather than being left behind. An empty config
    # contains no profiles, so an inherited name raises ProfileNotFound -- a confusing failure in a
    # session whose whole point is needing no profile. `build_bedrock_model` routes a named profile
    # away from here before that can bite, which is precisely why it would go unnoticed.
    inner = botocore.session.Session(session_vars={
        "profile":          (None, None, None, None),
        "config_file":      (None, None, os.devnull, None),
        "credentials_file": (None, None, os.devnull, None),
    })
    return boto3.Session(botocore_session=inner, region_name=region)


def build_bedrock_model(model_id: str | None, streaming: bool | None = None):
    """A Bedrock model, authenticated by API key if there is one and by ordinary AWS credentials
    otherwise.

    THE KEY GOES INTO THE ENVIRONMENT, which is a process-global mutation and worth saying out loud.
    `BedrockModel` has no `api_key` parameter because bearer-token auth is not a boto3 credential --
    botocore reads `AWS_BEARER_TOKEN_BEDROCK` itself when the client is constructed. Setting it here
    is the supported route, not a workaround.

    No key is a normal configuration, not an error: boto3 then finds credentials the usual way, from
    `~/.aws` or an instance role, which is what a deployed container would use.
    """
    import boto3
    from strands.models import BedrockModel

    if (key := bedrock_api_key()):
        os.environ[BEDROCK_TOKEN_ENV] = key

    region = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
              or setting("Bedrock:Region"))

    # A named profile, for naming a DIFFERENT ACCOUNT. Note that it is NOT an authentication setting
    # when a key is present: the bearer token supersedes whatever credentials the profile yields, so
    # a profile holding expired keys behaves exactly like one holding good ones.
    profile = os.environ.get("AWS_PROFILE") or setting("Bedrock:Profile")

    session = (boto3.Session(profile_name=profile, region_name=region) if profile
               else keyed_session(boto3, region) if isolate_from_shared_config(key, profile)
               else None)

    # The region rides on the SESSION when there is one. `BedrockModel` raises "Cannot specify both
    # `region_name` and `boto_session`", so passing both -- which a configured profile and a
    # configured region would have done -- fails before any request is made.
    where = {} if session else {"region_name": region}

    # model_id is left out when not given so that BedrockModel picks its own regional default; a
    # hardcoded one here would name a model the account may not have enabled.
    config = {"model_id": model_id} if model_id else {}

    # Some models accept tools only OUTSIDE streaming mode -- `ai21.jamba-1-5-large-v1:0` answers
    # "This model doesn't support tool use in streaming mode", and this agent is nothing but tool
    # use. Configurable rather than guessed from the model id, which would be a list to maintain.
    if streaming is None and (configured := setting_raw("Bedrock:Streaming")) is not None:
        streaming = configured not in (False, "false", "False", "0", 0)
    if streaming is not None:
        config["streaming"] = streaming

    try:
        return BedrockModel(boto_session=session, **where, **config)
    except Exception as e:
        # Name the cause. The raw error is "Missing Dependency: ... pip install botocore[crt]",
        # which describes a package rather than the configuration that reached for it.
        #
        # Reaching here means the shared config WAS read -- so either a profile is named, or there
        # is no API key to authenticate with instead. Both are answerable without installing
        # anything, which is why neither branch below recommends the package.
        if "crt" in str(e) or "login credential provider" in str(e):
            why = (f'the profile "{profile}" was named, so the AWS config was read'
                   if profile else
                   "no Bedrock API key is configured, so ordinary AWS credentials were required")
            fix = ('drop the profile setting and authenticate by key instead, or name a profile '
                   'that does not use `login_session`'
                   if profile else
                   'put a key in "ApiKeys": {"AmazonBedrock": "..."} -- the AWS config is then not '
                   "read at all -- or make the default profile usable")
            raise SystemExit(
                f"Bedrock could not build a client: {e}\n\n"
                "This is the AWS credential chain, not the API key. `create_client` resolves "
                "credentials BEFORE it consults the bearer token and then discards them, since "
                "bearer auth supersedes SigV4 at signing -- so a chain that raises takes the "
                "client down over a value that was never going to be used. A `[default]` profile "
                "carrying `login_session` reaches a CRT-backed provider and raises.\n\n"
                f"Here, {why}.\n\nTo fix it, {fix}. Installing the optional botocore[crt] also "
                "works and is what the message suggests, but it is not required for key auth.") from e
        raise


def gemini_api_key() -> str | None:
    """The Gemini key, from the environment or from appsettings.json.

    Environment first. Not because it is the nicer way to work -- on Windows it is markedly worse,
    which is why the file exists -- but because a deployment injects one, and an injected secret
    should win over a file that happened to come along for the ride.
    """
    for name in GEMINI_KEYS:
        if os.environ.get(name):
            return os.environ[name]

    return setting(GEMINI_SETTING)


def build_model(provider: str = "auto", model_id: str | None = None,
                streaming: bool | None = None):
    """The model to reason with, or None for the Strands default.

    `auto` picks Gemini when an API key is in the environment and Bedrock otherwise. That ordering
    is not a preference between them: a key that is present was put there deliberately, whereas
    Bedrock credentials sit in `~/.aws` on most machines whether or not the account can actually
    call a model. Preferring the explicit signal fails less confusingly.
    """
    if provider == "auto":
        provider = "gemini" if gemini_api_key() else "bedrock"

    if provider == "bedrock":
        return build_bedrock_model(model_id, streaming)

    if provider != "gemini":
        raise SystemExit(f"unknown provider {provider!r}; expected 'bedrock', 'gemini' or 'auto'")

    try:
        from strands.models.gemini import GeminiModel
    except ImportError as e:
        # The provider MODULE ships with strands-agents; only the SDK underneath it is missing, so
        # say which one rather than letting "No module named 'google'" stand as the explanation.
        raise SystemExit(
            f"the Gemini provider needs the google-genai SDK, which is not installed ({e}).\n"
            "It is a pinned dependency like every other: add it to requirements/strands/"
            "requirements.in, recompile the lock, and install by hand. See requirements/README.md."
        ) from e

    args = gemini_client_args()
    if "api_key" not in args:
        raise SystemExit(
            "no Gemini API key. Put one in an appsettings.json beside src/agent/ (or at the repo "
            f'root) as {{"ApiKeys": {{"GoogleAgentPlatform": "..."}}}}, or set one of '
            f"{' or '.join(GEMINI_KEYS)}. See src/agent/appsettings.json.example.")

    if args.get("enterprise") and not args.get("project"):
        raise SystemExit(
            "Google:Enterprise is set but Google:Project is not. An Agent Platform key needs a "
            "project and a location; see src/agent/appsettings.json.example.")

    return GeminiModel(client_args=args, model_id=model_id or DEFAULT_GEMINI_MODEL)


def review(request: str, project_dir: Path | None = None, model: str | None = None,
           provider: str = "auto", streaming: bool | None = None,
           transcript: Path | None = None, heading: str = "",
           limits: dict | None = None) -> str:
    """Run one review. Returns what the agent said.

    `transcript` writes the whole exchange -- every tool call, with its arguments and its full
    reply -- as markdown, APPENDING when the file already exists so several questions build one
    log. The prose an agent produces is a claim about what the tools returned; saving both is what
    lets somebody check the one against the other instead of taking it.

    `limits` caps the agent loop: `turns`, `total_tokens`, `output_tokens`. THIS is the agent with
    tools -- it can call the checker repeatedly, and a run that keeps re-asking is the one worth
    bounding. A cap does not raise: it comes back as a stop_reason, so it is reported below rather
    than left to look like a finished answer.
    """
    from strands import Agent

    client = anchor_server(project_dir)
    with client:
        tools = client.list_tools_sync()
        # callback_handler=None turns off Strands' default printer. Left on, it streams the answer
        # to stdout as it is generated AND we print the returned result, so the review arrives
        # twice — which reads as a bug in the checker rather than in the plumbing.
        agent = Agent(model=build_model(provider, model, streaming), tools=tools,
                      system_prompt=SYSTEM_PROMPT, callback_handler=None)
        result = agent(request, **({"limits": limits} if limits else {}))
        answer = str(result)

        # A CAP IS NOT AN ANSWER THAT FINISHED. It arrives as a stop_reason with the agent
        # returning normally, so nothing downstream can tell a bounded review from a complete one
        # unless it is said here -- and a half-finished review of a policy is exactly the kind of
        # thing a reader would act on believing it was the whole of it.
        stop = str(getattr(result, "stop_reason", "") or "")
        if stop.startswith("limit_"):
            answer += (f"\n\n**This review was stopped by the `{stop}` cap and is incomplete.** "
                       f"It may not have run every check it intended to. Raise the cap or ask a "
                       f"narrower question.")

        if transcript is not None:
            from agent import transcript as tr

            existing = transcript.read_text(encoding="utf-8") if transcript.exists() else ""
            if not existing:
                existing = tr.header("Agent transcript")
            transcript.write_text(
                existing.rstrip() + "\n\n"
                + tr.render(agent.messages, question=request, heading=heading,
                            meta={"provider": provider, "model": model or "(provider default)"}),
                encoding="utf-8")

        return answer


# What the far side says when it will not answer, and what that means for the person running this.
# Matched on the exception type where the SDK gives us one and on the message otherwise, because
# botocore's ClientError carries the interesting part only in its text.
REFUSALS = (
    ("Too many tokens per day",
     "The account's DAILY TOKEN BUDGET is spent. It resets; nothing is wrong with the setup."),
    ("Too many requests",
     "Rate limited. Wait and retry -- this is throughput, not quota."),
    ("Model use case details have not been submitted",
     "This model is not enabled for the account. Submit use case details in the Bedrock console, "
     "or pass --llm with one that is."),
    # Matched without the contraction: the message is "doesn't" for one model and "don't" for
    # another, and the first version of this line caught neither of them.
    ("support tool use in streaming mode",
     "This model will not take tools while streaming, and this agent is nothing but tool use. "
     "Re-run with --no-stream."),
    ("AccessDenied",
     "The credentials reached Bedrock and were refused. Check the key and the region."),
    ("API_KEY_SERVICE_BLOCKED",
     "A Google Agent Platform key needs the Google block -- Enterprise, Project, Location. See "
     "src/agent/appsettings.json.example."),
)


def explain(e: Exception) -> str | None:
    """What a far-side refusal means, or None if it is not one we recognise.

    Shared by the CLI and the AgentCore server so that a deployed failure reads the same as a local
    one. Returning None rather than a guess matters: an unrecognised error dressed up as a known
    one sends the reader somewhere there is nothing to find.
    """
    text = str(e)
    return next((meaning for needle, meaning in REFUSALS if needle.lower() in text.lower()), None)


def refused(e: Exception) -> int:
    """Report a far-side refusal as an outcome rather than a traceback.

    A QUOTA ERROR IS NOT A CRASH. It means every layer worked -- credentials, region, routing, tool
    negotiation -- and the account said no at the end. Thirty lines of Python stack describe none of
    that, and bury the one sentence that does.
    """
    if (meaning := explain(e)) is not None:
        print(f"the model refused: {str(e).splitlines()[0]}\n\n{meaning}", file=sys.stderr)
        return 2
    # Not one we recognise, so do not pretend to explain it. The full text, without the stack.
    print(f"{type(e).__name__}: {e}", file=sys.stderr)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("policy", type=str, help="a .dw policy file, relative to the project directory")
    ap.add_argument("--against", type=str, help="a second .dw file to compare against")
    ap.add_argument("--event-schema", type=str, help="the .dwschema the policy is deployed under")
    ap.add_argument("--project-dir", type=Path, default=REPO,
                    help="the directory policy paths are resolved inside (default: the repo)")
    ap.add_argument("--provider", type=str, default="auto",
                    choices=("auto", "bedrock", "gemini"),
                    help="which model provider. `auto` picks gemini when GEMINI_API_KEY or "
                         "GOOGLE_API_KEY is set, and bedrock otherwise")
    ap.add_argument("--llm", type=str, default=None,
                    help="the LLM's model id; defaults to the provider's own default")
    ap.add_argument("--no-stream", action="store_true",
                    help="disable streaming. Some Bedrock models accept tools only outside "
                         "streaming mode -- ai21.jamba answers 'This model doesn't support tool "
                         "use in streaming mode', and this agent is nothing but tool use")
    ap.add_argument("--transcript", type=Path, default=None, metavar="FILE.md",
                    help="append the whole exchange -- every tool call, its arguments and its "
                         "full reply -- to this markdown file. The prose is a claim; the tool "
                         "output is the evidence for it, and a transcript is what lets somebody "
                         "check the one against the other")
    ap.add_argument("--heading", type=str, default="",
                    help="a title for this exchange in the transcript")
    ap.add_argument("--ask", type=str, default=None,
                    help="ask something else about the policy instead of the standard review")
    # BOUNDING THE LOOP. This agent has the MCP tools, so it can keep calling the checker; these
    # are the caps on that. A trip is a stop_reason rather than an error, so the answer says it
    # was cut short instead of merely being shorter.
    ap.add_argument("--turns", type=int, default=None,
                    help="cap on loop iterations -- one model call plus the tools it asked for")
    ap.add_argument("--total-tokens", type=int, default=None,
                    help="cap on input+output tokens for this review")
    ap.add_argument("--output-tokens", type=int, default=None,
                    help="cap on generated tokens. Soft: checked at turn boundaries, so one "
                         "oversized response can overshoot")
    args = ap.parse_args()

    if args.ask:
        request = f"{args.ask}\n\nThe policy file is {args.policy}."
    else:
        request = (f"Review the policy at {args.policy}. Tell me whether every rule in it is doing "
                   f"something, and what I should be aware of about the answer.")

    # THE FILES GO IN EITHER WAY. These used to be appended only to the standard review, so
    # `--ask "... the second version ..." --against other.dw` asked a question about a file whose
    # path was never mentioned -- and the agent, reasonably, asked for it. A flag that silently
    # does nothing on one code path is worse than one that is not offered there.
    if args.against:
        request += f"\n\nThe second policy file, to compare against, is {args.against}."
    if args.event_schema:
        request += f"\n\nIt is deployed under the event schema {args.event_schema}."

    # A live model call, which costs money and reaches the network. Said plainly rather than
    # discovered on the bill.
    print(f"asking the model to review {args.policy} (this makes live model calls)\n",
          file=sys.stderr)

    try:
        print(review(request, args.project_dir, args.llm, args.provider,
                     streaming=False if args.no_stream else None,
                     transcript=args.transcript, heading=args.heading,
                     limits={k: v for k, v in (("turns", args.turns),
                                               ("total_tokens", args.total_tokens),
                                               ("output_tokens", args.output_tokens)) if v}))
    except Exception as e:  # noqa: BLE001 -- the far side refusing is an outcome, not a crash
        return refused(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
