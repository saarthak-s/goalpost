"""Contract tests for goalpost rules.

Each fixture in tests/fixtures/ is a .diff file paired with a .expected file.
Tests call the rule functions directly (no git binary needed, except one
test that verifies exit code 2 outside a repository).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from goalpost.gitdiff import filter_test_files, parse_diff
from goalpost.rules import analyze_file

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> tuple[str, list[dict]]:
    """Load a fixture by stem name. Return (diff_text, expected_findings)."""
    diff_path = FIXTURES_DIR / f"{name}.diff"
    expected_path = FIXTURES_DIR / f"{name}.expected"

    diff_text = diff_path.read_text(encoding="utf-8")

    expected = []
    for line in expected_path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            expected.append(json.loads(line))
    return diff_text, expected


def _run_fixture(name: str) -> tuple[list, list[dict]]:
    """Parse a fixture diff, run rules, return (findings, expected)."""
    diff_text, expected = _load_fixture(name)
    files = parse_diff(diff_text)
    test_files = filter_test_files(files)

    all_findings = []
    for df in test_files:
        # For new files, reconstruct new_text from diff
        new_text = None
        if df.is_new and df.hunks:
            new_text = "\n".join(text for hunk in df.hunks for _, text in hunk.added)
        findings = analyze_file(df, old_text=None, new_text=new_text)
        all_findings.extend(findings)

    return all_findings, expected


# ============================================================================
# Contract cases (MUST pass)
# ============================================================================


class TestContract:
    """The five contract cases from AGENTS.md."""

    def test_python_subscript_bare_truthiness_is_matcher_downgrade(self):
        """A comparison on a subscript changed to bare truthiness is high."""
        diff_text = """\
diff --git a/tests/test_contract.py b/tests/test_contract.py
index 1234567..abcdefg 100644
--- a/tests/test_contract.py
+++ b/tests/test_contract.py
@@ -1,2 +1,2 @@
 def test_counts():
-    assert data["counts"]["high"] == 1
+    assert data["counts"]["high"]
"""
        files = filter_test_files(parse_diff(diff_text))
        findings = analyze_file(files[0])

        assert [(finding.rule, finding.severity) for finding in findings] == [
            ("matcher-downgrade", "high")
        ]

    def test_contract_01_bound_loosened(self):
        """assert latency < 200 -> assert latency < 500 is HIGH bound-loosened."""
        findings, expected = _run_fixture("contract_01_bound_loosened")
        assert len(expected) == 1
        exp = expected[0]
        high = [f for f in findings if f.severity == "high"]
        assert len(high) >= 1, f"Expected high finding, got: {findings}"
        found = any(
            f.rule == exp["rule"] and f.file == exp["file"] and f.line == exp["line"]
            for f in high
        )
        assert found, f"Expected {exp}, got {[(f.rule, f.file, f.line) for f in high]}"

    def test_contract_02_matcher_downgrade(self):
        """toEqual(7) -> toBeTruthy() is HIGH matcher-downgrade."""
        findings, expected = _run_fixture("contract_02_matcher_downgrade")
        assert len(expected) == 1
        exp = expected[0]
        high = [f for f in findings if f.severity == "high"]
        assert len(high) >= 1, f"Expected high finding, got: {findings}"
        found = any(f.rule == exp["rule"] for f in high)
        assert found, f"Expected {exp}, got {[(f.rule, f.file, f.line) for f in high]}"

    def test_contract_03_retarget_info(self):
        """toBe(200) -> toBe(201) is INFO, not high."""
        findings, expected = _run_fixture("contract_03_retarget_info")
        high = [f for f in findings if f.severity == "high"]
        info = [f for f in findings if f.severity == "info"]
        assert len(high) == 0, (
            f"Should not have high findings, got: {[(f.rule, f.file) for f in high]}"
        )
        assert len(info) >= 1, f"Expected info finding, got: {findings}"
        assert any(f.rule == "retarget" for f in info)

    def test_contract_04_skip_removed(self):
        """Deleted it.skip(...) is NOT a finding."""
        findings, expected = _run_fixture("contract_04_skip_removed")
        high = [f for f in findings if f.severity == "high"]
        assert len(high) == 0, (
            f"Should not have findings, got: {[(f.rule, f.file) for f in high]}"
        )

    def test_contract_05_weak_new_test(self):
        """New test_retry.py with only 'assert result is not None' is HIGH weak-new-test."""
        findings, expected = _run_fixture("contract_05_weak_new_test")
        assert len(expected) == 1
        exp = expected[0]
        high = [f for f in findings if f.severity == "high"]
        assert len(high) >= 1, f"Expected high finding, got: {findings}"
        found = any(f.rule == exp["rule"] for f in high)
        assert found, f"Expected {exp}, got {[(f.rule, f.file, f.line) for f in high]}"

    def test_skipif_is_not_a_skipped_test_but_xfail_is(self):
        diff_text = """\
diff --git a/tests/test_media.py b/tests/test_media.py
index 1234567..abcdefg 100644
--- a/tests/test_media.py
+++ b/tests/test_media.py
@@ -1,3 +1,4 @@
+@pytest.mark.skipif(sys.platform == "win32", reason="needs ffmpeg")
 def test_transcode():
     assert transcode() == "ok"
"""
        findings = analyze_file(filter_test_files(parse_diff(diff_text))[0])
        assert not any(f.rule == "skip-added" for f in findings)

        diff_text = diff_text.replace(
            "@pytest.mark.skipif(sys.platform == \"win32\", reason=\"needs ffmpeg\")",
            "@pytest.mark.xfail(reason=\"known issue\")",
        )
        findings = analyze_file(filter_test_files(parse_diff(diff_text))[0])
        assert any(
            f.rule == "skip-added"
            and f.message == "test marked expected-to-fail"
            for f in findings
        )

    def test_is_none_remains_an_absence_assertion(self):
        diff_text = """\
diff --git a/tests/test_config.py b/tests/test_config.py
index 1234567..abcdefg 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -1,2 +1,2 @@
 def test_missing_config():
-    assert load_config().id == config.id
+    assert load_config().id is None
"""
        findings = analyze_file(filter_test_files(parse_diff(diff_text))[0])
        assert not any(f.rule == "matcher-downgrade" for f in findings)

    def test_high_finding_suppresses_same_line_retarget_info(self):
        diff_text = """\
diff --git a/tests/test_latency.py b/tests/test_latency.py
index 1234567..abcdefg 100644
--- a/tests/test_latency.py
+++ b/tests/test_latency.py
@@ -1,2 +1,2 @@
 def test_latency():
-    assert latency < 200
+    assert latency < 500
"""
        findings = analyze_file(filter_test_files(parse_diff(diff_text))[0])
        assert [finding.rule for finding in findings] == ["bound-loosened"]

        diff_text = """\
diff --git a/tests/test_items.py b/tests/test_items.py
index 1234567..abcdefg 100644
--- a/tests/test_items.py
+++ b/tests/test_items.py
@@ -1,2 +1,2 @@
 def test_items():
-    assert items == expected
+    assert len(items) == len(expected)
"""
        findings = analyze_file(filter_test_files(parse_diff(diff_text))[0])
        assert [finding.rule for finding in findings] == ["matcher-downgrade"]

    def test_swallowed_catch_is_not_double_counted_as_assertion_removed(self):
        findings, _ = _run_fixture("error_swallowed_catch_js")
        assert [finding.rule for finding in findings] == ["error-swallowed"]

# ============================================================================
# All fixtures: parametrized
# ============================================================================


def _all_fixture_names() -> list[str]:
    """Get all fixture stem names."""
    names = set()
    for p in FIXTURES_DIR.glob("*.diff"):
        names.add(p.stem)
    return sorted(names)


@pytest.mark.parametrize("fixture_name", _all_fixture_names())
def test_fixture(fixture_name):
    """Run each fixture and verify findings match expected."""
    findings, expected = _run_fixture(fixture_name)
    high = [f for f in findings if f.severity == "high"]
    info = [f for f in findings if f.severity == "info"]

    if len(expected) == 1 and "none" in expected[0]:
        # No finding expected — no high findings allowed
        assert len(high) == 0, (
            f"Fixture {fixture_name}: expected no high findings, "
            f"got {[(f.rule, f.file, f.line) for f in high]}"
        )
        return

    for exp in expected:
        severity = exp.get("severity", "high")
        rule = exp.get("rule")
        if severity == "high":
            matched = [f for f in high if f.rule == rule]
            assert len(matched) >= 1, (
                f"Fixture {fixture_name}: expected high {rule}, "
                f"got high={[(f.rule, f.file) for f in high]}"
            )
        elif severity == "info":
            matched = [f for f in info if f.rule == rule]
            assert len(matched) >= 1, (
                f"Fixture {fixture_name}: expected info {rule}, "
                f"got info={[(f.rule, f.file) for f in info]}"
            )


# ============================================================================
# CLI exit code test
# ============================================================================


def test_cli_exit_2_outside_repo(tmp_path):
    """goalpost should exit 2 when run outside a git repo."""
    result = subprocess.run(
        [sys.executable, "-m", "goalpost.cli"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert result.returncode == 2


def test_cli_from_repo_subdirectory(tmp_path):
    """The CLI resolves worktree paths when invoked below the repo root."""
    repo = tmp_path / "repo"
    nested = repo / "tools"
    tests_dir = repo / "tests"
    nested.mkdir(parents=True)
    tests_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    test_file = tests_dir / "test_latency.py"
    test_file.write_text("def test_latency():\n    assert latency < 200\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "baseline"], cwd=repo, check=True)
    test_file.write_text("def test_latency():\n    assert latency < 500\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "goalpost.cli"],
        capture_output=True,
        text=True,
        cwd=nested,
        env=env,
    )

    assert result.returncode == 1
    assert "bound-loosened" in result.stdout


def test_demo_exits_1():
    """goalpost demo should exit 1 (it has a high finding)."""
    result = subprocess.run(
        [sys.executable, "-m", "goalpost.cli", "demo"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "bound-loosened" in result.stdout
    assert "tests/test_latency.py:12" in result.stdout


def test_demo_json():
    """goalpost demo --json should output valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "goalpost.cli", "demo", "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["counts"]["high"] == 1
    assert data["high"][0]["rule"] == "bound-loosened"
    assert data["high"][0]["file"] == "tests/test_latency.py"
    assert data["high"][0]["line"] == 12
