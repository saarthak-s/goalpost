"""Text and JSON renderers for findings."""

from __future__ import annotations

import json
from typing import TextIO

from goalpost.rules import Finding


def render_text(findings: list[Finding], out: TextIO) -> int:
    """Render findings as plain text. Return exit code (0 or 1)."""
    high_count = 0
    info_count = 0

    for f in findings:
        if f.severity == "high":
            high_count += 1
            prefix = "high"
        else:
            info_count += 1
            prefix = "info"

        loc = f.file
        if f.line is not None:
            loc += f":{f.line}"

        out.write(f"{prefix}  {f.rule}  {loc}\n")
        if f.old is not None:
            out.write(f"  - {f.old}\n")
        if f.new is not None:
            out.write(f"  + {f.new}\n")
        out.write(f"  {f.message}\n")
        out.write("\n")

    # Summary line
    if high_count > 0:
        out.write(f"{high_count} high. Exit 1.\n")
        return 1
    else:
        out.write(f"0 high. Exit 0.\n")
        return 0


def render_json(findings: list[Finding], out: TextIO) -> int:
    """Render findings as JSON. Return exit code (0 or 1)."""
    high = []
    info = []

    for f in findings:
        entry = {
            "rule": f.rule,
            "file": f.file,
            "line": f.line,
            "old": f.old,
            "new": f.new,
            "message": f.message,
        }
        if f.severity == "high":
            high.append(entry)
        else:
            info.append(entry)

    result = {
        "high": high,
        "info": info,
        "counts": {"high": len(high), "info": len(info)},
    }

    out.write(json.dumps(result, indent=2))
    out.write("\n")

    return 1 if high else 0
