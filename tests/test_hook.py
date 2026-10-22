"""Tests for the Claude Code Stop-hook integration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from goalpost.hook import install_hook, run_hook
from goalpost.rules import Finding

SRC = str(Path(__file__).resolve().parent.parent / "src")

HIGH = Finding(
    rule="bound-loosened", severity="high", file="tests/test_x.py", line=3,
    old="assert t < 200", new="assert t < 500", message="same comparison, wider bound.",
)
INFO = Finding(
    rule="retarget", severity="info", file="tests/test_x.py", line=9,
    old="a", new="b", message="expected value changed",
)


def _collect(findings, rc=0):
    return lambda: (rc, findings)


def test_warn_mode_never_blocks():
    out = json.loads(run_hook("{}", _collect([HIGH])))
    assert "decision" not in out
    assert "bound-loosened" in out["systemMessage"]
    assert "Exit" not in out["systemMessage"]


def test_clean_scan_prints_nothing():
    assert run_hook("{}", _collect([])) == ""


def test_info_only_prints_nothing():
    assert run_hook("{}", _collect([INFO])) == ""


def test_block_mode_blocks_with_reason():
    out = json.loads(run_hook("{}", _collect([HIGH]), block=True))
    assert out["decision"] == "block"
    assert "assert t < 500" in out["reason"]
    assert "revert" in out["reason"]


def test_block_mode_does_not_loop():
    payload = json.dumps({"stop_hook_active": True})
    out = json.loads(run_hook(payload, _collect([HIGH]), block=True))
    assert "decision" not in out
    assert "systemMessage" in out


def test_fails_open_on_scan_error():
    assert run_hook("{}", _collect([], rc=2)) == ""


def test_fails_open_on_exception():
    def boom():
        raise RuntimeError("x")
    assert run_hook("{}", boom, block=True) == ""


def test_fails_open_on_garbage_stdin():
    out = json.loads(run_hook("not json", _collect([HIGH])))
    assert "systemMessage" in out


def test_long_output_is_capped():
    many = [HIGH] * 12
    msg = json.loads(run_hook("{}", _collect(many)))["systemMessage"]
    assert "+7 more" in msg


# -- install_hook ----------------------------------------------------------

def test_install_creates_file(tmp_path):
    p = tmp_path / ".claude" / "settings.json"
    install_hook(p, "goalpost hook")
    data = json.loads(p.read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0] == {"type": "command", "command": "goalpost hook"}


def test_install_preserves_existing_settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other.sh"}]}],
                  "PreToolUse": [{"matcher": "Bash", "hooks": []}]},
    }))
    install_hook(p, "goalpost hook")
    data = json.loads(p.read_text())
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    assert "PreToolUse" in data["hooks"]
    cmds = [h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert cmds == ["other.sh", "goalpost hook"]


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "s.json"
    install_hook(p, "goalpost hook")
    assert "already" in install_hook(p, "goalpost hook")
    assert len(json.loads(p.read_text())["hooks"]["Stop"]) == 1


def test_install_updates_mode(tmp_path):
    p = tmp_path / "s.json"
    install_hook(p, "goalpost hook")
    assert "updated" in install_hook(p, "goalpost hook --block")
    stop = json.loads(p.read_text())["hooks"]["Stop"]
    assert len(stop) == 1 and stop[0]["hooks"][0]["command"] == "goalpost hook --block"


def test_install_refuses_invalid_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{ broken")
    with pytest.raises(ValueError):
        install_hook(p, "goalpost hook")
    assert p.read_text() == "{ broken"


# -- end to end ------------------------------------------------------------

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@b.c")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tests").mkdir()
    f = tmp_path / "tests" / "test_latency.py"
    f.write_text("def test_fast():\n    latency = 1\n    assert latency < 200\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _run_cli(cwd, stdin, *args):
    env = {**os.environ, "PYTHONPATH": SRC}
    return subprocess.run(
        [sys.executable, "-m", "goalpost", *args],
        cwd=cwd, input=stdin, capture_output=True, text=True, env=env,
    )


def test_e2e_hook_flags_loosened_bound(repo):
    f = repo / "tests" / "test_latency.py"
    f.write_text(f.read_text().replace("< 200", "< 500"))
    r = _run_cli(repo, json.dumps({"cwd": str(repo)}), "hook")
    assert r.returncode == 0
    assert "bound-loosened" in json.loads(r.stdout)["systemMessage"]


def test_e2e_hook_silent_when_clean(repo):
    r = _run_cli(repo, json.dumps({"cwd": str(repo)}), "hook")
    assert r.returncode == 0 and r.stdout == ""


def test_e2e_hook_block_mode(repo):
    f = repo / "tests" / "test_latency.py"
    f.write_text(f.read_text().replace("< 200", "< 500"))
    r = _run_cli(repo, "{}", "hook", "--block")
    assert json.loads(r.stdout)["decision"] == "block"


def test_e2e_hook_outside_repo_is_silent(tmp_path):
    r = _run_cli(tmp_path, "{}", "hook")
    assert r.returncode == 0 and r.stdout == ""


def test_e2e_hook_scans_untracked_test_file(repo):
    untracked = repo / "tests" / "test_untracked.py"
    untracked.write_text(
        "def test_placeholder():\n"
        "    result = calculate()\n"
        "    assert result is not None\n"
    )
    r = _run_cli(repo, json.dumps({"cwd": str(repo)}), "hook")
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert "weak-new-test" in out["systemMessage"]
    assert "test_untracked.py" in out["systemMessage"]
    assert "weakened test change(s)" in out["systemMessage"]


def test_plain_cli_scans_untracked_test_file(repo):
    untracked = repo / "tests" / "test_untracked.py"
    untracked.write_text(
        "def test_placeholder():\n"
        "    result = calculate()\n"
        "    assert result is not None\n"
    )
    r = _run_cli(repo, "", "--json")
    assert r.returncode == 1
    assert "weak-new-test" in r.stdout


def test_e2e_install_hook_cli(repo):
    r = _run_cli(repo, "", "install-hook", "--block")
    assert r.returncode == 0
    data = json.loads((repo / ".claude" / "settings.json").read_text())
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "goalpost hook --block"
