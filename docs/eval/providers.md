# Model providers and profiles

The harness calls models through named **profiles** in `config/models.json`. A run picks
a generator profile and a judge profile. The defaults come from `config/eval.json`
(`"generator": "claude_code_sonnet"`, `"judge": "claude_code_opus"`), and you can override
them for one command:

```
adr-eval run gov --system baseline-rrf --generator claude_code_sonnet --judge openai
adr-eval golden gov --gen --generator claude_code_sonnet --judge claude_code_opus --max-calls 2000
adr-eval doctor            # one line per profile: ok / missing key ENV / placeholder model
adr-eval doctor --live claude_code_haiku   # also make a 1-token call
```

`golden --gen` needs both profiles configured: the judge decides paraphrased free-text
answers in the evidence-only check (a verbatim match skips it). `--max-calls` counts
generator and judge calls together; cache hits are free. `golden --gen` has no
`--max-dollars` and no price pre-check: with an API profile, cap it with `--max-calls`.
`golden --verify` makes no model calls and refuses `--generator`, `--judge` and
`--max-calls`.

`--max-calls` counts logical calls: a call that is retried after an error (see Retries
below) counts once, however many attempts it took.

No key is ever written to a file. An API profile reads its key from the environment
variable named in its `api_key_env`.

## The profiles

| Profile | Adapter | Billing | Needs |
|---|---|---|---|
| `claude_code_sonnet`, `claude_code_opus`, `claude_code_haiku` | `claude_code` | Claude subscription | the `claude` CLI, logged in |
| `anthropic_sonnet` | `anthropic` (SDK) | API, priced from `config/prices.json` | `ANTHROPIC_API_KEY` |
| `openai`, `gemini`, `deepseek`, `openrouter` | `openai_compatible` | API | the profile's key env var and a real `model` |
| `selfhost` | `openai_compatible` against `http://localhost:8000/v1` | none (your server) | `SELFHOST_API_KEY` (any value if the server ignores it) and a real `model` |

A `model` (or `family`) that starts with `<set` is a placeholder. `doctor` reports that
profile as `placeholder model`, and a run that names it stops before any work.

### `claude_code`: headless Claude Code as a plain model

Each call runs:

```
claude -p --model <model> --output-format json --max-turns 1 --safe-mode \
  --disable-slash-commands --no-session-persistence --system-prompt <system> --tools ""
```

The user message goes on stdin. The flags make the CLI behave like a plain model call:

- `--system-prompt` replaces Claude Code's own system prompt. It does not append to it.
- `--tools ""` removes every built-in tool.
- `--safe-mode` turns off hooks, plugins, MCP servers and CLAUDE.md.
- `--disable-slash-commands` drops the skill listing.

A live check on CLI 2.1.319 showed no tools and no MCP servers, with about 1.3k input
tokens of residual harness context. Without `--safe-mode`, the installed plugins' MCP tools
and SessionStart hooks were still loaded.

The profiles pin full model IDs (`claude-sonnet-5-5`, `claude-opus-5-5`,
`claude-haiku-5-5`), not the aliases `sonnet` / `opus` / `haiku`. An alias can move to a
newer model, and the cache would then mix answers from two models under one key. With a
full ID the cache key is exact for the model.

The model that actually answered is read from the keys of the envelope's `modelUsage`.
It is recorded as `served_models` on each row and, per role, as a sorted list in
`config.json`. If any served model differs from the profile's model ID, `config.json`
gets `served_model_mismatch: true` and the report warns. The API adapters record the
model named in the response the same way.

The CLI is started without `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` in its
environment. In non-interactive mode, `claude -p` authenticates with
`ANTHROPIC_API_KEY` whenever that variable is set. Without the scrub, adding the key for
`anthropic_sonnet` would silently move every `claude_code` call onto API billing, while
`config.json` still said "subscription" and `--max-dollars` bounded nothing. The
variables stay set for the harness itself. Only the `claude` child process loses them.

The same scrub removes the Bedrock, Vertex and Foundry switches (`CLAUDE_CODE_USE_BEDROCK`,
`CLAUDE_CODE_USE_VERTEX`, `CLAUDE_CODE_USE_FOUNDRY`). Two things cannot be detected from
the harness: an `apiKeyHelper` in Claude Code's settings, and a CLI logged in with a
Console (API) account instead of a subscription. Either bills the calls to the API outside
the subscription while the run records them as $0. Check that `claude` is logged in with
your subscription before a large run.

The adapter depends on the CLI's `--max-turns` flag, which keeps each call to one model
turn. A CLI release that drops or renames it breaks the adapter.

Limits compared with the API adapters:

- The CLI has no max-tokens or temperature flag. `max_tokens` only goes into the cache
  key, and sampling uses the CLI's default, not temperature 0. `config.json` records this
  as `"sampling": "cli-default (temperature not pinned)"` for the role. API adapters
  record `"temperature 0"`.
- Input tokens are counted as `input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens` from the CLI's JSON envelope.

Cost: `config/prices.json` has `"claude_code:*": {"billing": "subscription"}`, so these
calls cost $0 against `--max-dollars`. The CLI's `total_cost_usd` (what the call would cost
at list API prices) is stored on each result row as `notional_cost_usd`. It is
informational only and is never counted toward `--max-dollars`. `config.json` records
`"billing": "subscription"` for the role. To bound subscription use, pass
`--max-calls N`. It stops before the model call that would exceed N. Cache hits are not
counted, and the run ends with `status: "stopped_calls"`.

Retries: a non-zero exit, `is_error: true`, a missing `result` or a 300 s timeout is
retried with the usual 1, 2, 4, 8, 16 s backoff.

## Usage limits and resuming

A failed call whose output looks like a subscription usage-limit message ("limit" with
"reset" or "usage") counts as a usage limit. So does a successful-looking reply in the CLI's
own phrasing: it starts with "You've hit your" or contains "limit · resets". That second
kind is never cached as an answer. For either kind, the client waits 60, 120, 240, 480 and 900 s between attempts,
about 30 minutes in total. If the limit still holds, the call fails with `ModelError`. The
row is then recorded with outcome `error`, and the run continues.

Every completed call is cached in `.cache/llm`, keyed by adapter, model, prompts,
`max_tokens` and repeat. The key does not include the endpoint's base URL, so never point
one profile name (or two profiles with the same adapter and model) at two different
endpoints: answers from both would share cache entries. To resume after a limit resets, rerun the same command. Finished
calls come from the cache for free, and only the missing ones reach the model. Errors are
not cached. If a run is clearly stuck behind a limit, stop it (Ctrl-C) and rerun after the
reset. Use `--max-calls` to size a run to the remaining allowance. A run or golden
generation stopped by `--max-calls` resumes the same way. Golden generation writes
nothing when it is stopped, because dedup and splits need the whole set.

## When a key arrives

1. Add the key through the environment's secure credential form (never in a file or in
   chat), under the variable named in the profile's `api_key_env`. Adding
   `ANTHROPIC_API_KEY` does not change how the `claude_code` profiles are billed: the
   harness removes it from the `claude` process's environment.
2. Set the profile's `model` in `config/models.json`. For `openrouter`, also set `family`.
   Add the model's price to `config/prices.json` (`input_per_mtok`, `output_per_mtok`,
   `as_of`; use 0.0 for a self-hosted model). A run refuses an unpriced model.
3. Run `adr-eval doctor --live <profile>` and expect `<profile>: ok`.
4. Re-judge an existing run with the new judge:
   `adr-eval run <corpus> --system <system> --split <split> --judge <profile>`. The
   generator calls are identical, so they come from the cache. Only the judge calls are
   new, and `--max-dollars` bounds them.

## Why the same-family judge flag matters

A judge from the same model family as the generator tends to favour that family's answers
(self-preference bias), which inflates accuracy. Each run records both families in
`config.json`, and sets `same_family_judge` when they match. The report then warns "judge
and generator share a model family". The default Claude Code profiles (Sonnet generating,
Opus judging) are both `anthropic`, so baseline numbers recorded with them carry that
warning. Re-judging with a different family (for example `openai` or `gemini`) once a key
is available removes the warning and shows how much the same-family judge moved the
scores.

## Text extraction and corpus builds

The golden sets' character offsets index into the extracted text. PDF extraction was
recorded with pypdf 7.0.0 **without fontTools installed** (pypdf logs "fontTools is
required ..." for some fonts). Installing fontTools can change the extracted text of those
PDFs and break the research golden set's offsets, so keep it out of the environment.
Build corpora in a clean `data/` directory: files left over from another snapshot are not
in any manifest and only cause confusion.

## Exit codes

`adr-eval` exits 0 on success, 2 on a usage or setup problem (missing files, an unconfigured
profile), 3 when a run or golden generation stops at `--max-calls` or `--max-dollars`, and 4
when `run` or `report` finds a determinism violation (the same question returned different
ranked lists across repeats).
