# Model providers: Amazon or Google

The reviewing agent in [`src/agent`](../src/agent) needs a model. It can use **Amazon Bedrock** or
**Google Gemini**, and nothing else in Anchor changes when you switch — the checker, the translator,
the TLA+ models and the MCP server are all model-free. Only the last step, the one that turns a
verdict into a sentence a person reads, needs an account.

```bash
python src/agent/policy_agent.py tests/policies/dead_forbid.dw                   # auto
python src/agent/policy_agent.py tests/policies/dead_forbid.dw --provider gemini
python src/agent/policy_agent.py tests/policies/dead_forbid.dw --provider bedrock
```

`--provider auto` is the default and **prefers Gemini when a key is configured**. That asymmetry is
deliberate: an API key in `appsettings.json` was put there by a person on purpose, whereas `~/.aws`
exists on most developer machines whether or not the account can call a model. A file that exists is
weaker evidence of intent than a key someone pasted.

| | Amazon Bedrock | Google Gemini |
|---|---|---|
| provider class | `strands.models.BedrockModel` | `strands.models.gemini.GeminiModel` |
| ships with `strands-agents`? | yes, and boto3 is already a dependency | the module ships; the `google-genai` SDK underneath it is a separate pin |
| extra package needed | **none** — boto3 is already there, and the `botocore[crt]` the error message asks for is avoidable; see below | `google-genai`, already in `requirements.in` |
| default model | `Bedrock:Model`, else the provider's regional default | `Gemini:Model`, else `gemini-2.5-flash` |
| credential shape | bearer token **in the environment**, or ordinary AWS credentials | API key |
| verified end to end here | authenticated, routed, tool-negotiated — generation blocked by account quota | **yes, including in the container** |

Both are configured the same way: environment variable first, then `appsettings.json`. Copy
[`src/agent/appsettings.json.example`](../src/agent/appsettings.json.example) to `appsettings.json`
beside it and fill in what you need. That file is gitignored by `**/*appsettings.json`; the
`.example` is not, because the pattern ends at `.json`. **Keep it that way — the example must never
hold a real key.**

## Choosing the model

`--llm <model-id>` names it for one run. To name it once, set the provider's `Model`:

```json
{
  "Gemini":  { "Model": "gemini-3.7-flash" },
  "Bedrock": { "Region": "us-east-1", "Model": "global.anthropic.claude-sonnet-4-6" }
}
```

One per provider, because a model id means nothing to the other one. The order is `--llm`, then the
setting, then the default in the table above; every mode uses the same order (`anchor check --full`,
`auto`, `hitl`, the pipeline), and an audit's summary says which of the three it used. Gemini's
setting is in a block of its own rather than in `Google`, because the `Google` block is left out for
an ordinary Developer API key.

**`anchor check --full --provider auto` means "use whatever is configured here, and stop if it cannot
be reached".** `--provider`, `--llm` and `--config` each make an audit's LLM *required*: before any
check runs, a one-token test request goes through the same client the questions will use, and a bad
key, an unknown model, a model the account may not call or one that cannot take tools stops the run
there with exit 3. Without any of them the LLM is optional, and a problem is a warning.

## Google Gemini

```json
{
  "ApiKeys": { "GoogleAgentPlatform": "..." }
}
```

or `GEMINI_API_KEY` / `GOOGLE_API_KEY` in the environment.

**An Agent Platform key is not an ordinary Developer API key, and the difference is not cosmetic.**
A Developer API key works with the block above and nothing else. An Agent Platform key additionally
needs the client put into enterprise mode with a project and a location, and *without* them it fails
with `403 API_KEY_SERVICE_BLOCKED` — a message that reads like a revoked key rather than a missing
constructor argument:

```json
{
  "ApiKeys": { "GoogleAgentPlatform": "..." },
  "Google": { "Enterprise": true, "Project": "your-project-id", "Location": "global" }
}
```

The equivalents are `GOOGLE_GENAI_ENTERPRISE`, `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`.
Leave the whole `Google` block out for a Developer key.

## Amazon Bedrock

```json
{
  "ApiKeys": { "AmazonBedrock": "..." },
  "Bedrock": { "Region": "us-east-1" }
}
```

**`Region` is required here**, for the same reason the `Google` block is required for an Agent
Platform key: authenticating by key means the surrounding machine configuration is not consulted, so
anything it would have supplied has to be stated. `AWS_REGION` works too.

Four things about Bedrock are not obvious, and each cost real time to find.

### The API key is a bearer token in the environment

`BedrockModel` has no `api_key` parameter, and that is not an oversight — bearer-token auth is not a
boto3 credential. botocore builds the variable name from the *service's signing name*, which for
`bedrock-runtime` is `bedrock`, giving **`AWS_BEARER_TOKEN_BEDROCK`**. `build_bedrock_model` puts
`ApiKeys:AmazonBedrock` there for you. The name was confirmed against the installed botocore
(`_get_bearer_env_var_name`) rather than assumed, which was worth doing: had it been wrong, the
symptom would have been an ordinary credentials error with nothing pointing at the token.

No key at all is a normal configuration rather than an error. boto3 then resolves credentials the
usual way — `~/.aws`, or an instance role, which is what a deployed container uses.

### A Bedrock API key really is enough — once boto3 is stopped from reading `~/.aws`

AWS's [API keys announcement](https://aws.amazon.com/blogs/machine-learning/accelerate-ai-development-with-amazon-bedrock-api-keys/)
says the SDK "automatically detects your environment variable when you create an Amazon Bedrock
client", and shows `boto3.client("bedrock-runtime", region_name=...)` with no credentials at all.
**That is accurate about authentication and incomplete about construction**, and the gap is worth
understanding because the obvious fix is a native dependency nobody needs.

Bearer auth genuinely supersedes SigV4 — measured, by hooking `before-send` and aborting before any
network I/O: with a bearer token set *and* ordinary credentials available, the signed request
carries `Authorization: Bearer` and the credentials go unused.

But `Session.create_client` resolves the credential chain **before** it consults the token, and then
throws the result away. The chain is walked for nothing — and **a chain that raises takes the client
down over a value that was never going to be used.** The order is:

```
Environment → assume-role → assume-role-with-web-identity → sso → SharedCredentials
            → login → custom-process → SharedConfig → Ec2Config → Boto2Config
            → EcsContainer → Ec2InstanceMetadata
```

`login` sits sixth and is implemented over the AWS Common Runtime. It is reached only when nothing
earlier answers, so a `[default]` profile carrying `login_session`, with no other credentials
anywhere, lands exactly there:

```
MissingDependencyException: ... pip install "botocore[crt]"
```

**That message is honest but its advice is the expensive option.** Installing `botocore[crt]` pulls
`awscrt` — a native TLS/HTTP/signing library — into every install and into the arm64 image, to
satisfy a provider whose output is discarded. So Anchor does not install it.

Instead, **an API key means the machine's AWS config is irrelevant, and `keyed_session` stops it
being read**: the client is built on a `botocore.session.Session` whose `config_file` and
`credentials_file` both point at `os.devnull`. Nothing in the chain answers, `load_credentials()`
returns `None` rather than raising, and the bearer token carries the request. Scoped to the one
session rather than set through `AWS_CONFIG_FILE`, because this agent spawns child processes and a
global would follow them.

This **changes no behaviour** — the discarded credentials were discarded either way. It only removes
a failure mode, which is why it is the default when a key is configured rather than something to opt
into.

**The one consequence is that a region must be stated.** No profile is read, so there is no profile
region, and `Bedrock:Region` (or `AWS_REGION`) becomes required. That is the same bargain the Google
provider makes: authenticate by key, and state what the key does not carry.

| setting | effect |
|---|---|
| key, no profile | `~/.aws` is not read. **Region required.** The documented key-only path |
| `Bedrock:Profile` | explicit request to use that profile, so `~/.aws` *is* read |
| no key | ordinary AWS credentials are genuinely needed, so `~/.aws` *is* read |
| `Bedrock:UseAwsConfig` | forces it either way, overriding all of the above |

**On the profile setting.** It names a different *account*; while a key is present it is not an
authentication setting at all, because the token supersedes whatever credentials the profile yields.
A profile therefore need only be *resolvable*, not valid — which is why the one used while this was
written held expired keys for an afternoon without a single symptom. Use it to choose an account,
never to work around the chain.

### Region rides on the session, not beside it

`BedrockModel` raises *"Cannot specify both `region_name` and `boto_session`"*. A configured profile
*and* a configured region is an ordinary combination, and it failed before any request was made
until the region was moved onto the `Session`.

### Some models refuse tools while streaming

This agent is nothing but tool use, so a model that will not take tools in a stream cannot run it at
all. `ai21.jamba-1-5-large-v1:0` answers *"This model doesn't support tool use in streaming mode"*.

```json
{ "Bedrock": { "Streaming": false } }
```

or `--no-stream`, which swaps `ConverseStream` for `Converse`. Anthropic and Nova models stream
tools fine, so this is **opt-in rather than inferred from a model id** — inferring it would mean
maintaining a list of which models misbehave, and that list would be wrong within a month.

## What "verified" means for each of these

Gemini is verified end to end, container included: a real review, against a real policy, with the
qualifications attached.

Bedrock is verified **up to but not including generation**. On the account this was written against,
every layer answered correctly — the token authenticated, the profile resolved, the region routed,
the model was found, and with streaming off it accepted the tool definitions — and then the request
was refused with `ThrottlingException: Too many tokens per day`. That the daily cap is account-wide
and genuinely spent rather than a payload problem was established three ways: a full agent turn, an
eight-token probe, and the AWS CLI with plain IAM credentials, all refused identically.

This is worth stating precisely rather than as "Bedrock works" or "Bedrock doesn't". **An error from
the far side is evidence.** A rejection for quota means the request authenticated, authorised, and
reached a model — which is the entire question the wiring was meant to answer, answered without a
single successful generation. What is not established is that the model produces a *good* review,
and no amount of error-reading will establish that.

## Troubleshooting

| symptom | cause |
|---|---|
| `403 API_KEY_SERVICE_BLOCKED` | Agent Platform key without the `Google` block. Add `Enterprise`, `Project`, `Location` |
| `pip install "botocore[crt]"` | `~/.aws` was read — so either a profile is named, or no API key is configured. Supply a key and drop the profile; installing the extra also works but is not needed |
| `You must specify a region` | key auth does not read `~/.aws`, so set `Bedrock:Region` or `AWS_REGION` |
| `Cannot specify both region_name and boto_session` | fixed; if it returns, a region is being passed beside a session instead of on it |
| `This model doesn't support tool use in streaming mode` | `Bedrock:Streaming: false` or `--no-stream` |
| `Model use case details have not been submitted` | account state — the model is not enabled for it. Not wiring |
| `Too many tokens per day` | account quota, which resets. Not wiring |
| `404 NOT_FOUND ... was not found or your project does not have access` | Gemini through an Agent Platform key has no model by that id, or the project may not use it. Check `--llm` or `Gemini:Model` |
| `The provided model identifier is invalid` | no Bedrock model by that id in this region. Check `--llm` or `Bedrock:Model` |
| `on-demand throughput isn't supported` | the model is called through an inference profile: use the profile id (`us.`, `global.`), not the bare model id |
| `InvalidClientTokenId` from `aws sts get-caller-identity` | the named profile's keys are dead. Check the profile before blaming the key |
| the agent prints each answer twice | `callback_handler=None` is missing; streaming output and the return value both print |

## Adding a third provider

Strands ships several others (Anthropic, Ollama, LiteLLM, OpenAI). `build_model` in
[`policy_agent.py`](../src/agent/policy_agent.py) is the only place that would change, and the split
that makes this cheap is documented in [`src/agent/README.md`](../src/agent/README.md): everything
below the model is exercised by [`tests/strands/agent_wiring.py`](../tests/strands/agent_wiring.py),
which needs no credentials at all.

That split has already paid. Three providers exercised three different code paths through one
function, and the third — the one with the most limited quota, which never generated a token —
exposed two real bugs the other two could not reach.
