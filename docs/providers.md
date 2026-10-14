# Provider configuration

These interfaces describe the implemented adapters. Verify model access with the installed vendor client.

System 1 supports `jev`, `openai` (Responses API), `openai_compatible` (Chat Completions), and `codex` (subscription login). Systems 2 and 4 support `codex`, `claude_code`, `antigravity`, `gemini_cli`, `cursor`, and `openai_compatible`. API and Codex actors require an explicit model; CLI planners accept `model: null` for the vendor default. Codex verifies image support through its model list. Compatible planners upload actual image content and require a vision-capable endpoint.

```yaml
provider: dual
system1:
  provider: openai
  model: YOUR_API_MODEL_ID
  api_key_env: OPENAI_API_KEY
  params: {}
system2:
  provider: codex
  model: null
  params: {}              # Optional reasoning_effort for Codex or Claude
  timeout_s: 120
```

System 4 is enabled by default and inherits the resolved System 2 settings. Configure `system4.provider`/`model` or `--system4-provider`/`--system4-model` independently; `system4.enabled: false` disables it. Its conversation and workspace are separate. It is invoked for team and battle strategy, not each navigation step. Provider or plan failures pause execution for inspection. See [System 4](system4.md).

These overrides work for `run`, `sandbox`, `benchmark`, and `llm doctor`:

```bash
uv run nuzlocke llm doctor
uv run nuzlocke run --system2-provider claude_code --system2-model sonnet
uv run nuzlocke run --system2-provider antigravity --system2-model gemini-3.8-flash-low
uv run nuzlocke sandbox --from <run-id> --steps 10 --system2-provider codex
uv run nuzlocke run --system1-provider openai --system1-model YOUR_API_MODEL_ID
uv run nuzlocke sandbox --from <run-id> --steps 20 --system1-provider codex --system1-model gpt-6-luna --system2-provider codex --system2-model gpt-6.1-sol
uv run nuzlocke run --agents-config /path/to/agents.yaml
```

Changing a provider via CLI clears that role's inherited model and settings. Supply the new model when required. Custom endpoints use YAML `base_url`, `api_key_env`, and `structured_output: json_schema | json_object | prompt`. OpenAI uses strict Responses structured output. Compatible API responses are always validated locally, including prompt-only JSON. API and Codex actors select an offered action or explicitly abstain; they do not fabricate Jev probability distributions or use Jev confidence thresholds.

| Planner | Setup and interface |
|---|---|
| `codex` | Install Codex CLI; run `codex login` with ChatGPT. Uses app-server and a persistent thread. |
| `claude_code` | Install Claude Code; run `claude auth login`. Uses the unmodified subscription CLI, explicit conversation resume, and disabled tools. |
| `antigravity` | Install Antigravity CLI; run `agy` and sign in with Google. Uses a persistent headless conversation. `agy models` lists available model IDs; the default is `gemini-3.8-flash-low`. |
| `gemini_cli` | Install Gemini CLI; sign in with Google. Requires eligible Code Assist Standard/Enterprise access. Uses ACP, image content, and a deny-all tool policy. |
| `cursor` | Set `CURSOR_API_KEY`. Preserves the durable SDK agent and context compaction. |

**Gemini personal subscriptions:** Google [retired personal-account Gemini CLI access](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals). A cached login does not establish service eligibility. Use `antigravity` for Google's current personal subscription path. `gemini_cli` remains available for eligible Standard/Enterprise accounts.

Antigravity headless input is text-only, so its native `view_file` tool reads run-local copies of the screenshots. A custom agent and pre-tool hook restrict it to the current screenshots; successful reads are verified by a post-tool hook before accepting a plan. The runner writes only run-local configuration, without changing global agent settings. Its active permission mode must be `request-review` or `strict`. Use `params: {reasoning_effort: low}` to override effort if desired; `low`, `medium`, `high`, and `max` are supported. With an explicit `model: null`, the first available Gemini model is selected.

A Codex actor uses its own process and conversation, separate from the planner, with text-only state and a per-turn JSON choice schema. It uses the same vendor-owned login as the planner and needs no API key.

OAuth credentials stay in vendor storage; the runner does not extract tokens or send them to API endpoints. `llm doctor` checks local setup without inference. Model access, quota, and token validity are checked on use. API actors use separate API credentials and billing. There is no silent provider or billing fallback.

Authentication/model failures, timeouts, and malformed planner results pause dual-mode play. HTTP APIs have bounded retries; CLI retries are managed by the vendor, with a runner timeout. Press START after fixing the problem. A restarted process creates a fresh vendor conversation with persisted journal context. Changing planner provider/model/parameters on resume clears its old plan and route, preserves map observations and rule ledgers, and requests a fresh look. Selection applies at startup; there is no live switch.

Legacy files without explicit system blocks still map `jev`, `cursor`, and `planner` settings as before. Legacy `--provider cursor` and `--provider openai_compatible` retain single-provider orchestration.

Interface references: [Codex app server](https://learn.chatgpt.com/docs/app-server), [Claude headless CLI](https://code.claude.com/docs/en/headless), [Antigravity headless CLI](https://antigravity.google/docs/cli/headless/), [Antigravity hooks](https://antigravity.google/docs/hooks/), [Gemini ACP](https://geminicli.com/docs/cli/acp-mode/), [OpenAI Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses).

