# Local Git-hook CI

On `zai-claude-code` and customization branches, hosted workflows are manual-only (`workflow_dispatch`), matching the `zai-cli` strategy. Pushes, PRs, issue/comment events, and schedules do not automatically run Actions from these branches. Upstream `main` is preserved as imported; its own explicitly dispatched or upstream-defined runs are not disabled repository-wide. Hosted history and branch protections are not deleted or relaxed.

## Install once per clone

Use Python 3.10+, Git, Node.js/npm, TypeScript 5.9.3, and a Claude Code build supporting the mod APIs in `mods/types`. Create the dedicated environment and install prerequisites before pushing:

```text
python -m venv .venv-local-ci
```

Use `.venv-local-ci/bin/python` on Linux/macOS or `.venv-local-ci/Scripts/python.exe` on Windows as `<venv-python>`:

```text
<venv-python> -m pip install -r .github/requirements-local-ci.txt
npm install --no-save --package-lock=false typescript@5.9.3
<venv-python> .github/scripts/local_ci.py --install
<venv-python> .github/scripts/local_ci.py
```

The installer sets repository-local `core.hooksPath` to `.github/hooks` and refuses to replace a different hook configuration. Linked worktrees share the setting. Git for Windows runs the same LF-terminated shell hook. The hook selects the checkout's dedicated Python environment when available, otherwise Python on PATH; it never installs dependencies during a push. The runner prefers a checkout-local `node_modules/.bin/tsc`, falling back to PATH. Install prerequisites in each customization worktree that needs them, or use compatible tools on PATH.

The original shared checkout must not be edited or switched by an agent to install these files. If it remains on upstream `main`, it does not contain our hook implementation; work in an isolated customization checkout. Cloning does not automatically install a hook. Browser edits, forge merges, and clients that bypass Git hooks do not provide local validation evidence.

During first adoption, publish the implementation before enabling the hook. Validate and explicitly disclose inherited failures for that bootstrap; do not claim they passed. Once installed, no bypass is allowed to publish a failing tree.

## Gate contract

Every non-deletion push runs the full applicable suite, not a changed-path subset. Outgoing commit tips must equal clean committed HEAD; annotated tags are peeled. The index, worktree, and untracked files must be clean both before and after validation. Check out and validate each branch separately. Deletion-only pushes have no outgoing source tree to test.

Without flags, `local_ci.py` also supports development checks on uncommitted changes. This is not a replacement for the hook's clean-commit check. Output streams live, a nonzero exit stops the gate, and each step has a positive finite timeout (default 1,200 seconds). Git preflights have 30-second deadlines; owned process cleanup has a 10-second deadline. Commands cannot read interactive input. Only validation-owned POSIX process groups or Windows jobs are stopped; task-local temporary output is removed on success or failure. The timeout/ownership implementation and regression tests are adapted from `zai-cli` commit `f72f28c7087efffcf97a671099b40e6bcdc34a6b`; keep portable fixes consistent while keeping command coverage repository-specific.

## Coverage

`.github/local-ci.json` defines the complete gate:

- Hook, clean-commit, failure/timeout, process-ownership, and policy regression tests.
- Manual-only workflow triggers and shared agent instruction/skill links.
- Existing workflow firewall, allow-list, and permission-mode hardening.
- Every integration's standard-library unit suite, including privacy tests once present.
- Copilot proxy authentication and native/translated protocol smoke tests with isolated fixture credentials, without real login or paid model calls.
- Typechecking every mod and running every enabled test, including upstream mods. The explicitly user-approved sec-default registration quarantine below is excluded and reported, not marked passed.
- Whitespace errors against committed HEAD.

The retained issue/comment workflows no longer receive automatic event payloads. Their forge actions are not run locally. Only dispatch handlers already designed for manual inputs should be invoked manually; retaining a workflow is not a promise that an issue-only handler works without its original payload. Advisory PR comments and issue-management analytics are consequently not automatic. Any new workflow imported during sync must be made manual-only before publishing a customization commit.

## Existing upstream compatibility failure

The published Claude Code 2.1.284 build rejects `prompt.compose` used by upstream `sec-default`. At the user's explicit request, only its 42 registration tests are disabled by retaining their unchanged source as `mods/sec-default/tests/register.disabled.ts`; the native runner discovers `.test.ts`/`.test.tsx`, not `.disabled.ts`. The other 15 sec-default tests still run. TypeScript still checks the disabled file, and the runtime security hook is unchanged. Both the local gate and manual Mod tests workflow use `check_mods.py`, which prominently reports this disabled coverage. A green gate is **not** evidence that registration security behavior was tested.

Restore the filename to `register.test.ts` when a compatible engine or legitimate upstream/API correction is available, then run the complete suite. No other checks are disabled, no pre-push bypass is permitted, and no security hook may be removed to make validation pass.

A pass on Linux is not native Windows/macOS evidence. Windows job assignment and Python redirector regressions require Windows; mark unavailable platforms as validation gaps. The local gate does not modify server merge rules or fix unrelated test failures.
