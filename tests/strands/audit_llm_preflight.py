"""What an audit does about its LLM, before and after the checks -- without ever calling one.

    python tests/strands/audit_llm_preflight.py

THE RULE BEING PINNED. The LLM is the optional part of an audit. With none of --llm, --provider or
--config, an LLM that cannot be had is a warning: the questions are skipped, every check runs, and
the report says why. Naming any of them is a request for LLM calls, so one that cannot be met stops
the run BEFORE its first TLC run (exit 3) -- or, if it fails only at the first question, after the
report is written (exit 3 again, so a script cannot read it as the findings exit).

It pins one bug in particular: `build_model` raises SystemExit for a missing key or region, and
`ask_model` caught only Exception, so an audit died after every check had run and before any of
them was written up.

NOTHING HERE CAN REACH A MODEL. The environment is emptied of every key and credential, the AWS
config files are pointed at os.devnull, instance metadata is off, the settings file is always one
this harness wrote, and `review` and `build_model` are replaced with stand-ins that raise.
The checks underneath are real: this runs TLC.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

CLEARED = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "AWS_BEARER_TOKEN_BEDROCK", "AWS_REGION",
           "AWS_DEFAULT_REGION", "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
           "AWS_SESSION_TOKEN", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
           "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_WEB_IDENTITY_TOKEN_FILE",
           "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_ENTERPRISE")
for name in CLEARED:
    os.environ.pop(name, None)
os.environ.update({"AWS_CONFIG_FILE": os.devnull, "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                   "AWS_EC2_METADATA_DISABLED": "true"})

from agent import audit, policy_agent  # noqa: E402
from agent.policy_agent import readiness  # noqa: E402

SECRET = "ANCHOR-TEST-NOT-A-KEY"


def no_model(*_args, **_kwargs):
    raise AssertionError("a model call was attempted")


real_probe = policy_agent.probe
probed: list[tuple] = []
probe_says: list[str | None] = [None]


def stand_in_probe(provider, model_id, streaming=None):
    probed.append((provider, model_id))
    return probe_says[0]


real_build_model = policy_agent.build_model
policy_agent.review = no_model
policy_agent.build_model = no_model
policy_agent.probe = stand_in_probe


class FakeModel:
    """Takes the probe's request and answers it, or raises what a provider would."""

    def __init__(self, fail: BaseException | None = None, params: dict | None = None):
        self.config = {"params": params} if params else {}
        self.fail, self.tools = fail, None

    def get_config(self):
        return self.config

    def update_config(self, **changes):
        self.config.update(changes)

    async def stream(self, messages, tool_specs=None, **_kwargs):
        self.tools = tool_specs
        if self.fail == "hang":
            await asyncio.sleep(3600)
        if self.fail:
            raise self.fail
        yield {"messageStop": {"stopReason": "max_tokens"}}

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{('  -- ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(label)


def settings(path: Path, content: dict) -> Path:
    path.write_text(json.dumps(content), encoding="utf-8")
    os.environ["ANCHOR_APPSETTINGS"] = str(path)
    return path


def run(argv: list[str]) -> tuple[int, str]:
    """audit.main() with this argv, and what it said on stderr."""
    said = io.StringIO()
    sys.argv = ["audit.py", *argv]
    with contextlib.redirect_stderr(said), contextlib.redirect_stdout(io.StringIO()):
        try:
            code = audit.main()
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, said.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="anchor-llm-test-") as tmp:
        work = Path(tmp)
        file = work / "appsettings.json"

        # --- readiness: what it finds, and that it never repeats a key ---------------------------
        settings(file, {"ApiKeys": {"GoogleAgentPlatform": SECRET}})
        r = readiness()
        check("auto picks gemini when a Gemini key is configured", r.provider == "gemini", r.provider)
        check("the key's source is the settings file, by path", r.source == str(file), r.source)
        check("a configured key is not a problem",
              not any("no Gemini API key" in p for p in r.problems), str(r.problems))
        check("readiness never holds the key itself", SECRET not in repr(r), repr(r))

        os.environ["GEMINI_API_KEY"] = SECRET
        r = readiness()
        check("the environment wins, and is named as the source", r.source == "$GEMINI_API_KEY", r.source)
        os.environ.pop("GEMINI_API_KEY")

        settings(file, {})
        r = readiness()
        check("with nothing configured auto falls to bedrock, and says nothing is configured",
              r.provider == "bedrock" and any("no LLM is configured" in p for p in r.problems),
              f"{r.provider} {r.problems}")
        r = readiness("gemini")
        check("gemini asked for with no key is a problem",
              any("no Gemini API key" in p for p in r.problems), str(r.problems))

        # A named file that is not there is NO file -- never the next one in the search -- and the
        # message must name it, not claim that nothing was named.
        os.environ["ANCHOR_APPSETTINGS"] = str(work / "typo.json")
        check("a missing ANCHOR_APPSETTINGS file is no file, not a fallback",
              policy_agent.appsettings_path() is None)
        r = readiness("gemini")
        check("...and the missing key's message names the missing path",
              any(f"names {work / 'typo.json'}, which does not exist" in p for p in r.problems),
              str(r.problems))

        # A key from the environment builds the LLM, and the missing file is STILL worth saying:
        # its Model or Region would silently stop applying. Said once, not per model built.
        os.environ["GEMINI_API_KEY"] = SECRET
        policy_agent._settings_warned = False
        r = readiness()
        check("a missing settings file is warned about even when the environment has the key",
              not r.problems and any("typo.json, which does not exist" in w for w in r.warnings),
              f"{r.problems} {r.warnings}")
        check("...once per process", not readiness().warnings)

        policy_agent._settings_warned = False
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            real_build_model("gemini")
            real_build_model("gemini")
        check("every LLM mode warns as it builds its model, once",
              said.getvalue().count("typo.json, which does not exist") == 1, said.getvalue())
        os.environ.pop("GEMINI_API_KEY")
        settings(file, {})

        settings(file, {"ApiKeys": {"AmazonBedrock": SECRET}})
        r = readiness()
        check("a Bedrock key with no region is a problem",
              any("no region" in p for p in r.problems), str(r.problems))
        settings(file, {"ApiKeys": {"AmazonBedrock": SECRET}, "Bedrock": {"Region": "us-east-1"}})
        r = readiness()
        check("a Bedrock key with a region is ready",
              not r.problems and r.source == str(file), f"{r.source} {r.problems}")
        check("the Bedrock key is not repeated either", SECRET not in repr(r), repr(r))
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

        # --- the model: --llm, then the provider's Model setting, then the default ---------------
        settings(file, {"ApiKeys": {"GoogleAgentPlatform": SECRET}, "Gemini": {"Model": "gemini-x"}})
        r = readiness()
        check("a Gemini:Model setting names the model when --llm does not",
              r.model == "gemini-x" and r.model_source == f"Gemini:Model in {file}",
              f"{r.model} / {r.model_source}")
        r = readiness(model_id="gemini-y")
        check("--llm wins over the setting", (r.model, r.model_source) == ("gemini-y", "--llm"),
              f"{r.model} / {r.model_source}")
        # Constructing the client sends nothing; only a request would.
        built = real_build_model("gemini")
        check("build_model runs the model the setting names",
              built.get_config().get("model_id") == "gemini-x", str(built.get_config()))

        settings(file, {"ApiKeys": {"GoogleAgentPlatform": SECRET}})
        r = readiness()
        check("with no setting, Gemini's default", (r.model, r.model_source) ==
              (policy_agent.DEFAULT_GEMINI_MODEL, "the provider's default"), f"{r.model} / {r.model_source}")

        settings(file, {"ApiKeys": {"AmazonBedrock": SECRET},
                        "Bedrock": {"Region": "us-east-1", "Model": "b-model"}})
        r = readiness()
        check("a Bedrock:Model setting names Bedrock's model", r.model == "b-model", r.model)
        settings(file, {"ApiKeys": {"AmazonBedrock": SECRET},
                        "Bedrock": {"Region": "us-east-1", "Model": ""}})
        r = readiness()
        check("an empty Model setting is no setting", r.model_source == "the provider's default",
              r.model_source)
        os.environ.pop("AWS_BEARER_TOKEN_BEDROCK", None)

        # --- the probe, against a stand-in model --------------------------------------------------
        fake = FakeModel()
        policy_agent.build_model = lambda *a, **k: fake
        check("an answered probe is no problem", real_probe("bedrock", "m") is None)
        check("the Bedrock probe is capped at one output token", fake.config.get("max_tokens") == 1,
              str(fake.config))
        check("the probe offers a tool, so a model that cannot take one refuses it here",
              [t["name"] for t in fake.tools or []] == ["noop"], str(fake.tools))

        fake = FakeModel(params={"temperature": 0})
        real_probe("gemini", "m")
        check("the Gemini probe is capped at one output token, keeping the other params",
              fake.config["params"] == {"temperature": 0, "max_output_tokens": 1}, str(fake.config))

        fake = FakeModel(fail=Exception("ValidationException: The provided model identifier is invalid."))
        said = real_probe("bedrock", "foo") or ""
        check("a bad model id fails the probe, and is explained", "no model by that id" in said, said)

        # The shape google-genai gives an Agent Platform 404: the sentence that matters sits inside
        # a printed dict, past where a fixed-width cut used to end the line.
        fake = FakeModel(fail=Exception(
            "404 NOT_FOUND. {'error': {'code': 404, 'message': 'Publisher model "
            "`projects/p/locations/global/publishers/google/models/foo` was not found or your "
            "project does not have access to it. Ensure you have access to the model and it is "
            "spelled correctly.', 'status': 'NOT_FOUND'}}"))
        said = real_probe("gemini", "foo") or ""
        check("an Agent Platform 404 is read out of its dict, whole",
              "404 NOT_FOUND: Publisher model" in said and "spelled correctly." in said
              and "{'error'" not in said, said)
        check("...and explained", "Google has no model by that name" in said, said)

        fake = FakeModel(fail="hang")
        policy_agent.PROBE_SECONDS, seconds = 1, policy_agent.PROBE_SECONDS
        said = real_probe("gemini", "slow") or ""
        policy_agent.PROBE_SECONDS = seconds
        check("a probe with no answer gives up rather than holding the run",
              "had no answer within 1s" in said, said)

        def exits(*_a, **_k):
            raise SystemExit("no key here")

        policy_agent.build_model = exits
        said = real_probe("gemini", "foo") or ""
        check("a client that cannot be built fails the probe rather than the process",
              "SystemExit: no key here" in said, said)
        policy_agent.build_model = no_model

        # --- the audit: one policy set, one question ----------------------------------------------
        policies = work / "policies"
        policies.mkdir()
        shutil.copy(REPO / "tests" / "policies" / "dead_forbid.dw", policies)
        (policies / "questions.md").write_text(
            "### 1. Is it doing anything?\n*Policy:* `dead_forbid.dw`\n> Is every rule needed?\n",
            encoding="utf-8")

        settings(file, {})
        ran = []
        real_check_all = audit.check_all
        audit.check_all = lambda *a, **k: ran.append(1) or real_check_all(*a, **k)

        code, said = run([str(policies), "--provider", "gemini"])
        check("an LLM asked for by name that cannot be had stops the run, exit 3",
              code == 3 and "not run: --provider" in said, f"{code}\n{said}")
        check("...before the first TLC run", not ran)
        check("...and says what is missing", "no Gemini API key" in said, said)

        code, said = run([str(policies), "--llm", "x", "--no-llm"])
        check("--llm and --no-llm together are refused", code == 2 and not ran, f"{code}\n{said}")

        out = work / "warned"
        code, said = run([str(policies), "--output-dir", str(out)])
        text = (out / "findings.md").read_text(encoding="utf-8") if (out / "findings.md").exists() else ""
        check("with none named, a missing LLM is a warning and the audit runs",
              "warning: no LLM is configured" in said and ran and code == 1, f"{code}\n{said}")
        check("the summary says, before the run, that the questions will not be asked",
              said.index("not asked: no LLM is configured") < said.index("[1/1]"), said)
        check("the report says why the questions were not asked",
              "| questions answered | 0 of 1 — not asked: no LLM is configured" in text, text[:1500])
        check("a set with no property module is warned about, not refused",
              "warning: no property module states what" in said, said)

        # --- a probe that fails, when the LLM was asked for by name ------------------------------
        settings(file, {"ApiKeys": {"GoogleAgentPlatform": SECRET}})
        ran.clear()
        probe_says[0] = "a one-token test request to foo via gemini failed: 404 NOT_FOUND"
        code, said = run([str(policies), "--llm", "foo"])
        check("--llm with a model the probe cannot reach stops the run, exit 3",
              code == 3 and "404 NOT_FOUND" in said and "not run: --llm" in said, f"{code}\n{said}")
        check("...before the first TLC run", not ran)
        check("...having probed the model named", probed[-1:] == [("gemini", "foo")], str(probed))
        probe_says[0] = None

        # --- a question that fails at the first call ---------------------------------------------
        settings(file, {"ApiKeys": {"GoogleAgentPlatform": SECRET}, "Gemini": {"Model": "gemini-x"}})
        policy_agent.review = exits
        probed.clear()
        out = work / "failed"
        code, said = run([str(policies), "--output-dir", str(out)])
        check("the summary names the model, and the setting it came from",
              "asked of gemini-x via gemini" in said and f"model: Gemini:Model in {file}" in said, said)
        text = (out / "findings.md").read_text(encoding="utf-8") if (out / "findings.md").exists() else ""
        check("a SystemExit from the LLM no longer loses the report",
              "questions answered | 0 of 1" in text and "SystemExit: no key here" in text, text[:1500])
        check("...and without --llm the exit is the findings exit", code == 1, f"{code}\n{said}")
        check("without --llm, --provider or --config nothing is spent on a probe", not probed,
              str(probed))

        out = work / "failed-explicit"
        code, said = run([str(policies), "--output-dir", str(out), "--llm", "some-model"])
        check("with --llm, a question that fails after a good probe writes the report and exits 3",
              code == 3 and (out / "findings.md").exists(), f"{code}\n{said}")
        check("...and the summary says the probe was answered",
              "a one-token test request was answered just now" in said, said)
        policy_agent.review = no_model
        audit.check_all = real_check_all

    print(f"\n{len(failures)} failure(s)" if failures else "\nall ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
