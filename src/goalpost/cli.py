"""CLI entry point: argparse, exit codes, text and JSON output."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from goalpost.gitdiff import DiffFile, filter_test_files, is_test_file, parse_diff
from goalpost.rules import Finding, analyze_file
from goalpost.hook import HOOK_COMMAND, install_hook, run_hook, settings_path
from goalpost.report import render_text, render_json


# Built-in demo fixture (the latency bound case from the README)
_DEMO_DIFF = """\
diff --git a/tests/test_latency.py b/tests/test_latency.py
index 1234567..abcdefg 100644
--- a/tests/test_latency.py
+++ b/tests/test_latency.py
@@ -10,4 +10,4 @@ def test_response_time():
     start = time.time()
     latency = measure()
-    assert latency < 200
+    assert latency < 500
"""


def _run_git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command. Return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 2, "", "git: command not found"
    except subprocess.TimeoutExpired:
        return 2, "", "git: command timed out"


def _get_diff(base: str | None, cwd: str | None = None) -> tuple[int, str]:
    """Get the diff text from git. Return (exit_code, diff_text).

    exit_code is 0 on success, 2 on git error.
    """
    if base is not None:
        # Verify the ref exists
        rc, _, stderr = _run_git("rev-parse", "--verify", base, cwd=cwd)
        if rc != 0:
            print(stderr.strip(), file=sys.stderr)
            return 2, ""
        args = ["diff", "--no-color", "--unified=3", f"{base}...HEAD"]
    else:
        args = ["diff", "--no-color", "--unified=3", "HEAD"]

    rc, stdout, stderr = _run_git(*args, cwd=cwd)
    if rc != 0:
        print(stderr.strip(), file=sys.stderr)
        return 2, ""
    return 0, stdout


def _get_old_text(path: str, base: str | None, cwd: str | None = None) -> str | None:
    """Get the old version of a file from git."""
    if base is not None:
        rc, merge_base, _ = _run_git("merge-base", base, "HEAD", cwd=cwd)
        if rc != 0:
            return None
        ref = merge_base.strip()
    else:
        ref = "HEAD"
    rc, stdout, stderr = _run_git("show", f"{ref}:{path}", cwd=cwd)
    if rc != 0:
        return None
    return stdout


def _get_new_text(path: str, cwd: str | None = None) -> str | None:
    """Read the current version of a file from the worktree."""
    try:
        full_path = os.path.join(cwd, path) if cwd else path
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IOError):
        return None


def _run_demo(use_json: bool) -> int:
    """Run the demo against built-in fixtures."""
    files = parse_diff(_DEMO_DIFF)
    test_files = filter_test_files(files)

    all_findings = []
    for df in test_files:
        findings = analyze_file(df)
        all_findings.extend(findings)

    if use_json:
        return render_json(all_findings, sys.stdout)
    else:
        return render_text(all_findings, sys.stdout)


def _collect_findings(
    base: str | None, *, include_untracked: bool = False
) -> tuple[int, list[Finding]]:
    """Scan the repo in the current directory. Return (exit_code, findings).

    exit_code is 0 on success (findings may be empty) and 2 on git error.
    """
    rc, repo_root, stderr = _run_git("rev-parse", "--show-toplevel")
    if rc != 0:
        print(stderr.strip(), file=sys.stderr)
        return 2, []
    repo_root = repo_root.strip()

    exit_code, diff_text = _get_diff(base, cwd=repo_root)
    if exit_code != 0:
        return exit_code, []

    test_files = filter_test_files(parse_diff(diff_text)) if diff_text.strip() else []
    all_findings = []
    for df in test_files:
        old_text = None
        new_text = None
        path = df.new_path or df.old_path
        if path and not df.is_deleted:
            new_text = _get_new_text(path, cwd=repo_root)
            old_text = _get_old_text(path, base, cwd=repo_root)
        all_findings.extend(analyze_file(df, old_text, new_text))

    if include_untracked:
        rc, output, stderr = _run_git(
            "ls-files", "--others", "--exclude-standard", cwd=repo_root
        )
        if rc != 0:
            print(stderr.strip(), file=sys.stderr)
            return 2, []
        for path in output.splitlines():
            path = path.strip()
            if not path or not is_test_file(path):
                continue
            new_text = _get_new_text(path, cwd=repo_root)
            if new_text is None:
                continue
            untracked = DiffFile(
                old_path=None,
                new_path=path,
                is_new=True,
            )
            all_findings.extend(analyze_file(untracked, new_text=new_text))

    all_findings.sort(key=lambda f: (
        f.file,
        f.line if f.line is not None else 0,
        f.rule,
    ))
    return 0, all_findings


def _install_hook_cmd(args) -> int:
    command = args.hook_command or (HOOK_COMMAND + (" --block" if args.block else ""))
    try:
        status = install_hook(settings_path(args.user), command)
    except ValueError as exc:
        print(f"goalpost: {exc}", file=sys.stderr)
        return 2
    print(f"goalpost Stop hook {status}")
    print(f"  command: {command}")
    print("  Restart Claude Code (or run /hooks) to load it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="goalpost",
        description="See where a diff made the tests easier to pass.",
    )
    parser.add_argument(
        "--base",
        metavar="REF",
        default=None,
        help="Compare REF...HEAD instead of working tree vs HEAD",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="use_json",
        help="Output findings as JSON",
    )
    parser.add_argument(
        "--block",
        action="store_true",
        help="hook/install-hook: ask Claude to revert or justify high findings",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="install-hook: write ~/.claude/settings.json instead of the project file",
    )
    parser.add_argument(
        "--hook-command",
        metavar="CMD",
        dest="hook_command",
        default=None,
        help="install-hook: command to register (default: 'goalpost hook')",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Subcommand (demo, hook, install-hook)",
    )

    args = parser.parse_args(argv)

    # Demo subcommand
    if args.command == "demo":
        exit_code = _run_demo(args.use_json)
        return exit_code
    elif args.command == "hook":
        out = run_hook(
            sys.stdin.read(),
            lambda: _collect_findings(None, include_untracked=True),
            block=args.block,
        )
        if out:
            sys.stdout.write(out + "\n")
        return 0
    elif args.command == "install-hook":
        return _install_hook_cmd(args)
    elif args.command is not None:
        parser.error(f"unknown command: {args.command}")

    exit_code, all_findings = _collect_findings(args.base, include_untracked=True)
    if exit_code != 0:
        return exit_code
    # Render
    if args.use_json:
        exit_code = render_json(all_findings, sys.stdout)
    else:
        exit_code = render_text(all_findings, sys.stdout)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
