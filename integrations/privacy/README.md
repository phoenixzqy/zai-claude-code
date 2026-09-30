# Claude Code privacy launcher

Launch the installed Claude Code with privacy opt-outs applied **before startup**, in either the interactive TUI or command-line mode. Python 3.9+ is sufficient; there are no extra dependencies. No global settings, credentials, or existing logs are edited or deleted.

```sh
python3 /path/to/zai-claude-code/integrations/privacy/claude.py
python3 /path/to/zai-claude-code/integrations/privacy/claude.py -- -p 'Explain this project'
python3 /path/to/zai-claude-code/integrations/privacy/claude.py -- --resume
python3 /path/to/zai-claude-code/integrations/privacy/claude.py --claude-binary /path/to/claude -- --model MODEL
```

The current directory is preserved. Terminal input/output is inherited directly; on POSIX the launcher replaces itself with Claude, preserving signals and exit codes rather than capturing or staging TUI output. Arguments are passed without a shell. Use `--` before Claude arguments. The `--settings` and `--setting-sources` options are reserved to prevent replacing this profile.

## One policy, two layers

The launcher reads the canonical [`.claude/settings.json`](../../.claude/settings.json), sets its environment values in the child process, and passes the same JSON through Claude's `--settings` option. This handles startup consumers and ordinary user/project settings that would otherwise overwrite shell variables. Organization-managed settings still take precedence: deploy these opt-outs there too if your organization configures telemetry. Changes made to settings while a session runs can also change behavior; this is not a tamper-proof policy.

The checked-in settings apply when working directly in this repository, but project settings cannot reliably configure every startup variable. **Use the launcher** when running elsewhere or when startup coverage matters. It does not change how a plain `claude` invocation outside this repository behaves.

| Area | Protection |
| --- | --- |
| First-party usage analytics | `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` |
| OpenTelemetry / OTLP | Telemetry enable flags off; SDK disabled; logs, metrics, and traces exporters set to `none`; content logging off |
| Inherited OTLP credentials and endpoints | All inherited `OTEL_*`, `TRACEPARENT`, `TRACESTATE`, and detailed beta tracing endpoint values removed before applying the policy |
| Remote error reports | `DISABLE_ERROR_REPORTING=1` |
| Feedback uploads and local feedback bundles | `/feedback`, `/bug`, `/share`, and Claude-drafted feedback disabled with the feedback switches and `feedbackDrafts: off` |
| TUI feedback and surveys | The same command opt-outs apply in the TUI; surveys disabled and the OTEL survey opt-in turned off |
| Source mod analytics | The [telemetry mod](../../mods/telemetry) validates and discards both first-party and collector calls without gathering context, credentials, or rows |

## TUI log staging and limits

Disabling the feedback entry points is intended to keep users out of the feedback preparation/upload workflow, including attaching or staging TUI logs for a report. **There is no public, verified switch here that independently disables all internal TUI log staging.** This repository does not contain the proprietary engine implementation, and these changes do not patch an installed binary. A source-level guarantee that no staging files are ever created requires access to that engine and an integration test of its feedback/error paths. Do not treat this launcher as that guarantee.

Local transcripts and debug logs remain local and are not disabled or purged by this profile. Model requests still send prompts and tool content to your configured provider. Authentication, plugins, MCP servers, hooks, tools, manually invoked commands, and repository-maintenance GitHub Actions may make their own network requests; their traffic is outside this runtime profile. In particular, repository issue-management Statsig events are not engine analytics and are unchanged. Strict no-egress requirements need a separately administered network sandbox, not just these opt-outs.

`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` also disables background updates and feature-flag fetching. Features depending on those flags, including Remote Control, can be unavailable. This does not weaken tool permissions, remove WebFetch safety checks, bypass managed policy, or alter provider authentication.

The Copilot gateway in PR #1 is independent and not part of this PR. It resolves `claude` on `PATH`, so combining them requires an executable shim named `claude` that invokes this privacy launcher with `--claude-binary` pointing to the real binary, forwarding the gateway's arguments after `--`. Do not point back at the shim (that would recurse), or change or copy credential handling here.

## Validation

```sh
python3 -B -m unittest discover -s integrations/privacy/tests -v
tsc -p mods/tsconfig.json
claude plugin test mods/telemetry
```

The launcher tests use fake executables and isolated temporary directories, with no real login or model request. They verify settings/environment propagation, argument handling, missing executables, exit status, and inherited terminals. Mod tests need a Claude build with `plugin test`; a missing command is a validation limitation, not a passing test. Real TUI feedback/error staging still needs engine-level validation.

Upstream references: [environment variables](https://code.claude.com/docs/en/env-vars), [environment precedence](https://code.claude.com/docs/en/settings-reference#env), and [data usage](https://code.claude.com/docs/en/data-usage).
