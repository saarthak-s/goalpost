"""Claude Code Stop-hook integration.

`goalpost hook` is meant to be registered as a Stop hook. It reads the hook
payload on stdin, scans the working tree against HEAD, and:

* warn mode (default): shows findings to the human, never interrupts Claude
* block mode (--block): asks Claude to revert or justify high findings, once

The hook must never break a session, so every internal failure is swallowed
and the hook exits 0 with no output ("fail open").
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Callable, Optional

from goalpost.report import render_text
from goalpost.rules import Finding

HOOK_COMMAND = "goalpost hook"
_MARK = "goalpost hook"  # substring that identifies our entry in settings.json
_MAX_SHOWN = 5


def _summarize(findings: list[Finding]) -> str:
    out = io.StringIO()
    shown = findings[:_MAX_SHOWN]
    render_text(shown, out)
    lines = out.getvalue().rstrip().splitlines()
    if lines and lines[-1].endswith("Exit 1.") or lines and lines[-1].endswith("Exit 0."):
        lines.pop()  # drop the CLI summary footer; meaningless inside a hook
    text = "\n".join(lines).rstrip()
    extra = len(findings) - len(shown)
    if extra > 0:
        text += f"\n(+{extra} more; run `goalpost` to see all)"
    return text


def run_hook(
    stdin_text: str,
    collect: Callable[[], tuple[int, list[Finding]]],
    block: bool = False,
) -> str:
    """Return the JSON string to print on stdout ('' means print nothing)."""
    try:
        try:
            payload = json.loads(stdin_text) if stdin_text.strip() else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        cwd = payload.get("cwd")
        if isinstance(cwd, str) and os.path.isdir(cwd):
            os.chdir(cwd)

        rc, findings = collect()
        if rc != 0:
            return ""
        high = [f for f in findings if f.severity == "high"]
        if not high:
            return ""

        if block and not payload.get("stop_hook_active"):
            reason = (
                "goalpost found test changes that make tests easier to pass:\n\n"
                + _summarize(high)
                + "\n\nIf these loosen a check only to get green, revert them and fix "
                "the code instead. If a change is intended, say so explicitly in your "
                "reply and explain why."
            )
            return json.dumps({"decision": "block", "reason": reason})

        # Warn mode (or block mode on the second pass): tell the human, don't interrupt.
        msg = "goalpost: " + str(len(high)) + " weakened test change(s)\n" + _summarize(high)
        return json.dumps({"systemMessage": msg})
    except Exception:
        return ""


def settings_path(user: bool, root: Optional[Path] = None) -> Path:
    if user:
        return Path.home() / ".claude" / "settings.json"
    return (root or Path.cwd()) / ".claude" / "settings.json"


def install_hook(path: Path, command: str) -> str:
    """Add (or update) the goalpost Stop hook in a Claude Code settings file.

    Idempotent. Refuses to touch a file that is not valid JSON. Returns a
    human-readable status line. Raises ValueError on an unusable file.
    """
    data: dict = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        if raw.strip():
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise ValueError(f"{path} is not valid JSON ({exc}); not modifying it")
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a JSON object; not modifying it")

    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"{path}: 'hooks' is not an object; not modifying it")
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        raise ValueError(f"{path}: 'hooks.Stop' is not a list; not modifying it")

    status = "installed"
    for group in stop:
        for h in (group.get("hooks", []) if isinstance(group, dict) else []):
            if isinstance(h, dict) and _MARK in str(h.get("command", "")):
                if h.get("command") == command:
                    return f"already installed in {path}"
                h["command"] = command
                path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                return f"updated in {path}"

    stop.append({"hooks": [{"type": "command", "command": command}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return f"{status} in {path}"
