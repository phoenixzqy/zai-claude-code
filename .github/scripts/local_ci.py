#!/usr/bin/env python3
"""Run the repository's local validation gate and install its Git hook."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ".github/hooks"
CONTROL_TIMEOUT = 30
CLEANUP_TIMEOUT = 10


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True,
        timeout=CONTROL_TIMEOUT,
    ).strip()


def install(root: Path) -> None:
    current = subprocess.run(
        ["git", "-C", str(root), "config", "--get", "core.hooksPath"],
        text=True, capture_output=True,
        timeout=CONTROL_TIMEOUT,
    )
    if current.returncode not in (0, 1):
        raise RuntimeError(f"Cannot inspect core.hooksPath: {current.stderr.strip()}")
    if current.stdout.strip() not in ("", HOOKS):
        raise RuntimeError(
            "An existing core.hooksPath is configured; integrate the pre-push "
            "hook explicitly rather than overwriting it.",
        )
    subprocess.run(
        ["git", "-C", str(root), "config", "--local", "core.hooksPath", HOOKS],
        check=True, timeout=CONTROL_TIMEOUT,
    )
    print(f"Installed {HOOKS}/pre-push for this checkout.", flush=True)


def pushed_head(root: Path, updates: str) -> str | None:
    """Reject pushes that would validate a different tree from the outgoing tip."""
    commits = set()
    for line in updates.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise RuntimeError("Malformed Git pre-push update record.")
        local_ref, local_sha, _remote_ref, remote_sha = fields
        if not all(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", sha)
                   for sha in (local_sha, remote_sha)):
            raise RuntimeError("Malformed Git pre-push object ID.")
        if set(local_sha) == {"0"}:
            continue
        try:
            commits.add(git(root, "rev-parse", "--verify", local_sha + "^{commit}"))
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Cannot validate non-commit ref {local_ref}.") from error
    if not commits:
        return None
    head = git(root, "rev-parse", "HEAD")
    if commits != {head}:
        raise RuntimeError(
            "Push tips must resolve to the checked-out HEAD. Check out and "
            "validate each branch separately; do not bypass the hook.",
        )
    require_clean(root, head)
    return head


def require_clean(root: Path, head: str) -> None:
    if git(root, "rev-parse", "HEAD") != head:
        raise RuntimeError("HEAD changed during validation; push aborted.")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError(
            "Pre-push requires a clean worktree and index, including untracked "
            "files, so tests validate the outgoing commit. Commit or stash first.",
        )


def stop_process(process: subprocess.Popen | None, job=None) -> None:
    try:
        if job is not None:
            job.terminate()
        elif process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    finally:
        try:
            if process is not None:
                if job is not None and process.poll() is None:
                    process.kill()
                process.wait(timeout=CLEANUP_TIMEOUT)
        finally:
            try:
                if process is not None and process.stdin is not None:
                    process.stdin.close()
            finally:
                if job is not None:
                    job.close()


def run_step(root: Path, step: dict, output: Path) -> None:
    timeout = step.get("timeout_seconds", 1200)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise RuntimeError(f"{step['name']} requires a positive finite timeout_seconds.")
    replacements = {"{python}": sys.executable, "{output}": str(output)}
    args = [replacements.get(arg, arg) for arg in step["argv"]]
    search_path = str(root / "node_modules" / ".bin") + os.pathsep + os.environ.get("PATH", os.defpath)
    executable = shutil.which(args[0], path=search_path)
    if executable is None:
        raise RuntimeError(f"Missing executable {args[0]}; see docs/local-validation.md.")
    args[0] = executable
    cwd = root / step.get("cwd", ".")
    env = dict(os.environ)
    for key in ("GOOS", "GOARCH", "CGO_ENABLED", "GIT_DIR", "GIT_WORK_TREE",
                "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                "GIT_NAMESPACE", "ZAI_AGENT_STATUS_ADDR", "ZAI_AGENT_STATUS_TOKEN"):
        env.pop(key, None)
    env.update(step.get("env", {}))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    env["DISABLE_FEEDBACK_COMMAND"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    print(f"\n== {step['name']} ==\n{' '.join(args)}", flush=True)
    options = {"stdin": subprocess.DEVNULL}
    job = None
    if os.name == "nt":
        from local_ci_windows import WindowsJob
        wrapper_python = getattr(sys, "_base_executable", None)
        if not wrapper_python:
            raise RuntimeError("Cannot locate the base Python interpreter for process ownership.")
        job = WindowsJob()
        args = [wrapper_python, "-B", str(Path(__file__).with_name("local_ci_windows.py")), *args]
        options["stdin"] = subprocess.PIPE
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = None
    failure = None
    try:
        process = subprocess.Popen(args, cwd=cwd, env=env, **options)
        if job is not None:
            job.assign(process.pid)
            process.stdin.write(b"go\n")
            process.stdin.close()
        code = process.wait(timeout=timeout)
        if code:
            failure = f"{step['name']} failed with exit code {code}; push blocked."
    except subprocess.TimeoutExpired:
        failure = f"{step['name']} timed out after {timeout:g}s; push blocked."
    except KeyboardInterrupt:
        failure = f"{step['name']} interrupted; push blocked."
    except OSError as error:
        failure = f"{step['name']} could not run: {error}; push blocked."
    finally:
        try:
            if failure:
                try:
                    print(failure, file=sys.stderr, flush=True)
                except (OSError, ValueError) as error:
                    failure += f" Could not write diagnostic: {error}."
        finally:
            try:
                stop_process(process, job)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RuntimeError(
                    f"{failure or step['name']}: process cleanup failed: {error}; push blocked.",
                ) from error
    if failure:
        raise RuntimeError(failure)


def validate(root: Path) -> None:
    config = json.loads((root / ".github/local-ci.json").read_text(encoding="utf-8"))
    platform = {"win32": "windows", "darwin": "darwin", "linux": "linux"}.get(sys.platform)
    if platform is None:
        raise RuntimeError(f"Unsupported local validation platform: {sys.platform}")
    skipped = []
    with tempfile.TemporaryDirectory(prefix="local-ci-") as directory:
        for step in config["steps"]:
            if platform not in step.get("platforms", ["windows", "darwin", "linux"]):
                skipped.append(step["name"])
                continue
            run_step(root, step, Path(directory))
    print(f"\nLocal validation passed on {platform}.", flush=True)
    print("Other native platforms remain unverified unless tested explicitly.", flush=True)
    if skipped:
        print("Not applicable on this host: " + ", ".join(skipped), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true", help="install the pre-push hook")
    mode.add_argument("--pre-push", action="store_true", help="consume Git ref updates on stdin")
    args = parser.parse_args(argv)
    try:
        if args.install:
            install(ROOT)
            return 0
        head = None
        if args.pre_push:
            head = pushed_head(ROOT, sys.stdin.read())
            if head is None:
                print("No outgoing commit tips to validate (deletion-only push).")
                return 0
        validate(ROOT)
        if head is not None:
            require_clean(ROOT, head)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Local validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
