# telemetry

In the `zai-claude-code` customization branch, this mod validates and discards analytics instead of collecting or exporting them. Both `anthropic` and `collector` destinations are consumed without forwarding to the engine. Built-in callers keep the existing asynchronous contract and malformed entries still reject. The existing caller-tier gate continues to refuse installed and administrator-prepended plugins.

No rows are queued, context or credentials read, probes run, timers scheduled, or HTTP requests made. `telemetryOf()` has no transport dependencies and `flush()` does nothing. The `engine.create` fold still adds the noun only when the engine has none; hooks consume calls on an existing engine noun too.

This source mod is not automatically installed into the separately distributed Claude Code binary. It covers plugin telemetry only, not the engine's internal analytics, OpenTelemetry, error reports, or feedback UI. Use the [privacy launcher](../../integrations/privacy/README.md) for those documented runtime opt-outs. Native TUI log-staging internals are not available in this repository.

## Validation

```sh
tsc -p mods/tsconfig.json
claude plugin test mods/telemetry
```

The mod test command requires a Claude Code build that provides `plugin test` and function hooks.
