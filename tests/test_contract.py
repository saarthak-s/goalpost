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
