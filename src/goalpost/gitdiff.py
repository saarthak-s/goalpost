"""Parse unified diffs and classify test files."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# Test-file globs as regex patterns
_TEST_PATTERNS = [
    re.compile(r"(^|/)test_[^/]*\.py$"),
    re.compile(r"(^|/)[^/]*_test\.py$"),
    re.compile(r"(^|/)tests/.*\.py$"),
    re.compile(r"(^|/)[^/]*\.test\.(js|ts|tsx)$"),
    re.compile(r"(^|/)[^/]*\.spec\.(js|ts|tsx)$"),
    re.compile(r"(^|/)__tests__/.*\.(js|ts|tsx)$"),
]


def is_test_file(path: str) -> bool:
    """Return True if *path* matches any test-file glob."""
    for pat in _TEST_PATTERNS:
        if pat.search(path):
            return True
    return False


@dataclass
class Hunk:
    """One @@ block inside a diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    removed: list[tuple[int, str]] = field(default_factory=list)  # (old_lineno, text)
    added: list[tuple[int, str]] = field(default_factory=list)  # (new_lineno, text)
    context: list[tuple[int, str]] = field(default_factory=list)  # (new_lineno, text)


@dataclass
class DiffFile:
    """One file in a unified diff."""

    old_path: Optional[str]  # None for new files
    new_path: Optional[str]  # None for deleted files
    is_deleted: bool = False
    is_new: bool = False
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)


_DIFF_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(text: str) -> list[DiffFile]:
    """Parse a unified diff string into a list of DiffFile objects."""
    files: list[DiffFile] = []
    current: Optional[DiffFile] = None
    current_hunk: Optional[Hunk] = None
    old_lineno = 0
    new_lineno = 0

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for line in lines:
        # New file header
        m = _DIFF_HEADER.match(line)
        if m:
            current = DiffFile(old_path=m.group(1), new_path=m.group(2))
            files.append(current)
            current_hunk = None
            continue

        if current is None:
            continue

        # Detect deleted / new / binary
        if line.startswith("deleted file"):
            current.is_deleted = True
            current.new_path = None
            continue
        if line.startswith("new file"):
            current.is_new = True
            current.old_path = None
            continue
        if line.startswith("Binary files"):
            current.is_binary = True
            continue

        # Skip --- / +++ lines
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            continue

        # Hunk header
        m = _HUNK_HEADER.match(line)
        if m:
            current_hunk = Hunk(
                old_start=int(m.group(1)),
                old_count=int(m.group(2)) if m.group(2) is not None else 1,
                new_start=int(m.group(3)),
                new_count=int(m.group(4)) if m.group(4) is not None else 1,
            )
            current.hunks.append(current_hunk)
            old_lineno = current_hunk.old_start
            new_lineno = current_hunk.new_start
            continue

        if current_hunk is None:
            continue

        # Diff content
        if line.startswith("-"):
            current_hunk.removed.append((old_lineno, line[1:]))
            old_lineno += 1
        elif line.startswith("+"):
            current_hunk.added.append((new_lineno, line[1:]))
            new_lineno += 1
        elif line.startswith(" ") or line == "":
            # context line (may be empty at end of diff)
            if line.startswith(" "):
                current_hunk.context.append((new_lineno, line[1:]))
            old_lineno += 1
            new_lineno += 1
        elif line.startswith("\\"):
            # "\ No newline at end of file" - skip
            continue

    return files


def filter_test_files(files: list[DiffFile]) -> list[DiffFile]:
    """Keep only files whose path matches a test-file glob."""
    result = []
    for f in files:
        path = f.new_path or f.old_path
        if path and is_test_file(path):
            result.append(f)
    return result
