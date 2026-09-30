# Repository instructions

Guidance for Claude Code and other coding agents working in this repository.

## Branches and pull requests

- `main` mirrors the upstream `anthropics/claude-code` repository. Reserve it for upstream synchronization; do not put our customizations there.
- `zai-claude-code` is our main working and integration branch for customizations.
- Start task branches from the latest `origin/zai-claude-code`. Target every customization PR at `zai-claude-code`, not `main`, unless the user explicitly asks for a different base. Pass the base explicitly when creating a PR; do not rely on GitHub's default branch.
- Add the `zai` label to customization PRs.
- Use an isolated worktree before editing, switching branches, building, testing, or generating files. Never switch or modify the shared source checkout. Release the worktree after work and preserve requested deliverables.
- Remove verified task-owned temporary files and stop only task-owned processes before handing off. Do not delete shared caches or other sessions' artifacts.

## Shared instructions and skills

`AGENTS.md` is the canonical instruction file. `CLAUDE.md` and `.github/copilot-instructions.md` are relative symbolic links to it. Edit `AGENTS.md`, not separate copies.

Project skills are exposed through `.agents/skills`. Each entry links to the original skill directory under `plugins/`, including its references and scripts. `.claude/skills`, `.codex/skills`, and `.github/skills` link to this shared directory. Edit the original plugin skill, not a duplicate. Preserve relative links and keep skill names lowercase and hyphenated to support cross-agent discovery.

Agents that do not automatically discover these paths should read `AGENTS.md` and applicable `.agents/skills/*/SKILL.md` files explicitly. Shared discovery does not make Claude-specific plugin APIs, commands, or tools available in another agent: use a skill only when its subject applies, and adapt tool calls to the current agent's capabilities.

## Repository scope

This repository contains Claude Code documentation, plugins, mods, and examples, not the proprietary CLI engine source. Provider integrations must use supported configuration or a clearly documented external gateway; do not claim a plugin changes the engine's native authentication or model provider.

## Privacy defaults

- `.claude/settings.json` is the single source of truth for runtime privacy opt-outs; the privacy launcher reads it rather than maintaining another copy.
- Keep plugin telemetry disabled for both first-party and collector destinations. Preserve entry validation and caller-tier permissions.
- Do not re-enable analytics, OpenTelemetry exporters, remote error reports, feedback commands, or surveys in our runtime defaults.
- Runtime opt-outs do not constitute an engine source patch or a network sandbox. Do not claim internal TUI log staging is verified without engine-level evidence.

## Security hardening for GitHub Actions

Workflow jobs in this repository that call Claude run with three protections.
Keep them when you add or edit a workflow.

1. **Egress-firewall runner.** The job has `runs-on: ubuntu-24.04-firewall`,
   a GitHub-hosted runner that filters the job's outbound network traffic. Do
   not move a job that calls Claude to another runner.
2. **Network allow list.** `.github/egress-firewall.yaml` lists the hosts
   those jobs may reach, besides any that GitHub's firewall allows by default.
   Keep `mode: enforce`, which is what makes the firewall block the rest. Follow
   that file's header when you add a host.
3. **Auto permission mode.** Every step that runs the Claude Code action
   (`uses: anthropics/claude-code-action`, or a local action with a
   `claude_args` input) passes `--permission-mode auto` in `claude_args`. A tool
   call that needs permission and that the allowed tools do not cover then runs
   only if Claude Code's safety review passes it. Allow only the tools the job
   needs, and keep any `--disallowedTools` list a step has. Use `claude-opus-4-6`
   or a newer model: on an older one Claude Code falls back to its default
   permission mode.

`claude.yml` answers `@claude` mentions. The Claude Code action sets
`--permission-mode acceptEdits` for those, and the `--permission-mode auto` in
the workflow's `claude_args`, which comes after it, replaces it.

`.github/workflows/workflow-hardening.yml` fails when a job that runs the Claude
Code action or mentions `ANTHROPIC_FEDERATION_RULE_ID` breaks protection 1 or 3,
or when the allow list is missing, empty, not `mode: enforce`, or names a host
with `*`. It cannot see a job that calls Claude another way, so check new
workflows by hand too. If a job cannot meet protection 1 or 3, add it with the
reason to the matching exemption table in
`.github/scripts/check_workflow_hardening.py`. A job in `EXEMPT_FROM_AUTO_MODE`
must set no permission mode at all. Do not skip or weaken the check.

Keep each workflow's `permissions:` block minimal, and never print tokens or
environment variables in workflow logs.
