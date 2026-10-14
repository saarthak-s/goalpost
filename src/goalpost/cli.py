"""CLI entry point: argparse, exit codes, text and JSON output."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from goalpost.gitdiff import parse_diff, filter_test_files
from goalpost.rules import analyze_file
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


def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git command. Return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except FileNotFoundError:
        return 2, "", "git: command not found"
    except subprocess.TimeoutExpired:
        return 2, "", "git: command timed out"


def _get_diff(base: str | None) -> tuple[int, str]:
    """Get the diff text from git. Return (exit_code, diff_text).

    exit_code is 0 on success, 2 on git error.
    """
    if base is not None:
        # Verify the ref exists
        rc, _, stderr = _run_git("rev-parse", "--verify", base)
        if rc != 0:
            print(stderr.strip(), file=sys.stderr)
            return 2, ""
        args = ["diff", "--no-color", "--unified=3", f"{base}...HEAD"]
    else:
        args = ["diff", "--no-color", "--unified=3", "HEAD"]

    rc, stdout, stderr = _run_git(*args)
    if rc != 0:
        print(stderr.strip(), file=sys.stderr)
        return 2, ""
    return 0, stdout


def _get_old_text(path: str, base: str | None) -> str | None:
    """Get the old version of a file from git."""
    if base is not None:
        ref = base
    else:
        ref = "HEAD"
    rc, stdout, stderr = _run_git("show", f"{ref}:{path}")
    if rc != 0:
        return None
    return stdout


def _get_new_text(path: str) -> str | None:
    """Read the current version of a file from the worktree."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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
        "command",
        nargs="?",
        default=None,
        help="Subcommand (demo)",
    )

    args = parser.parse_args(argv)

    # Demo subcommand
    if args.command == "demo":
        exit_code = _run_demo(args.use_json)
        return exit_code
    elif args.command is not None:
        parser.error(f"unknown command: {args.command}")

    # Check we are in a git repo
    rc, _, stderr = _run_git("rev-parse", "--is-inside-work-tree")
    if rc != 0:
        print(stderr.strip(), file=sys.stderr)
        return 2

    # Get the diff
    exit_code, diff_text = _get_diff(args.base)
    if exit_code != 0:
        return exit_code

    if not diff_text.strip():
        if args.use_json:
            render_json([], sys.stdout)
        else:
            sys.stdout.write("0 high. Exit 0.\n")
        return 0

    # Parse and filter
    files = parse_diff(diff_text)
    test_files = filter_test_files(files)

    if not test_files:
        if args.use_json:
            render_json([], sys.stdout)
        else:
            sys.stdout.write("0 high. Exit 0.\n")
        return 0

    # Analyze each test file
    all_findings = []
    for df in test_files:
        old_text = None
        new_text = None
        path = df.new_path or df.old_path

        if path and not df.is_deleted:
            new_text = _get_new_text(path)
            old_text = _get_old_text(path, args.base)

        findings = analyze_file(df, old_text, new_text)
        all_findings.extend(findings)

    # Sort all findings by file, line, rule
    all_findings.sort(key=lambda f: (
        f.file,
        f.line if f.line is not None else 0,
        f.rule,
    ))

    # Render
    if args.use_json:
        exit_code = render_json(all_findings, sys.stdout)
    else:
        exit_code = render_text(all_findings, sys.stdout)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
