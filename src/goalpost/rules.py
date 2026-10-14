"""Pure rule functions: diff + old/new text -> findings."""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from typing import Optional

from goalpost.gitdiff import DiffFile, Hunk


# ---------------------------------------------------------------------------
# Finding data
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    rule: str
    severity: str  # "high" or "info"
    file: str
    line: Optional[int]
    old: Optional[str]
    new: Optional[str]
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Python unittest assert methods (closed list)
_PY_ASSERT_METHODS = frozenset([
    "assertEqual", "assertNotEqual", "assertTrue", "assertFalse",
    "assertIs", "assertIsNot", "assertIsNone", "assertIsNotNone",
    "assertIn", "assertNotIn", "assertRaises", "assertAlmostEqual",
    "assertGreater", "assertLess", "assertGreaterEqual", "assertLessEqual",
    "assertRegex",
])

# Strong oracles (Python)
_PY_STRONG_METHODS = frozenset([
    "assertEqual", "assertNotEqual", "assertAlmostEqual",
    "assertGreater", "assertLess", "assertGreaterEqual", "assertLessEqual",
    "assertIn", "assertNotIn", "assertIs", "assertIsNot", "assertRaises",
    "assertRegex",
])

# Weak oracles (Python)
_PY_WEAK_METHODS = frozenset([
    "assertTrue", "assertFalse", "assertIsNone", "assertIsNotNone",
])

# JS strong matchers
_JS_STRONG = frozenset([
    "toEqual", "toStrictEqual", "toBe", "toMatch", "toThrow",
    "toHaveBeenCalledWith", "toContain", "toHaveLength",
    "toHaveProperty", "toMatchObject", "toMatchSnapshot",
    "toMatchInlineSnapshot",
])

# JS weak matchers
_JS_WEAK = frozenset([
    "toBeTruthy", "toBeFalsy", "toBeDefined", "toBeUndefined",
    "toBeNull", "toBeNaN",
])

# Suppressions
_SUPPRESSION_PATTERNS = [
    re.compile(r"#\s*noqa"),
    re.compile(r"#\s*type:\s*ignore"),
    re.compile(r"#\s*pragma:\s*no\s*cover"),
    re.compile(r"//\s*@ts-ignore"),
    re.compile(r"//\s*@ts-expect-error"),
    re.compile(r"eslint-disable"),
]

# Skip patterns
_SKIP_PATTERNS_ADDED = [
    re.compile(r"@pytest\.mark\.skip"),
    re.compile(r"@pytest\.mark\.xfail"),
    re.compile(r"@unittest\.skip"),
    re.compile(r"pytest\.skip\("),
    re.compile(r"\.skip\s*\("),
    re.compile(r"\bxit\s*\("),
    re.compile(r"\bxdescribe\s*\("),
]

# Focus patterns (info only)
_FOCUS_PATTERNS = [
    re.compile(r"\.only\s*\("),
    re.compile(r"\bfit\s*\("),
    re.compile(r"\bfdescribe\s*\("),
]

# Bound detection
_BOUND_RE = re.compile(
    r"(.*?)\s*(<=?|>=?)\s*(\d+(?:\.\d+)?)\s*$"
)

_JS_BOUND_RE = re.compile(
    r"^(.*?)\.\s*(toBeLessThan|toBeLessThanOrEqual|"
    r"toBeGreaterThan|toBeGreaterThanOrEqual)\s*\(\s*"
    r"(\d+(?:\.\d+)?)\s*\)\s*;?\s*$"
)

# JS test block start
_JS_TEST_START = re.compile(
    r"^\s*(?:it|test)(?:\.only|\.skip)?\s*\("
)

# JS assertion line
_JS_ASSERTION_RE = re.compile(
    r"(?:expect\s*\(|assert\s*\.|assert\s*\()"
)

# JS matcher extraction
_JS_MATCHER_RE = re.compile(
    r"\.\s*(toEqual|toStrictEqual|toBe|toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|toBeNaN|toMatch|toThrow|toContain|toHaveLength|toHaveProperty|toMatchObject|toMatchSnapshot|toMatchInlineSnapshot|toHaveBeenCalledWith)\s*\("
)

# Python strong oracle patterns in a line
_PY_STRONG_LINE_RE = re.compile(
    r"(?:==|!=|assertEqual|assertNotEqual|assertAlmostEqual|assertGreater|assertLess|assertGreaterEqual|assertLessEqual|assertIn|assertNotIn|assertIs\b|assertIsNot\b|assertRaises|assertRegex)"
)

# Python weak oracle patterns in a line
_PY_WEAK_LINE_RE = re.compile(
    r"(?:assertTrue|assertFalse|assertIsNone|assertIsNotNone|assert\s+\w+\s+is\s+not\s+None|assert\s+\w+\s+is\s+None|\bassert\s+\w+\s*$)"
)


def _is_py_file(path: str) -> bool:
    return path.endswith(".py")


def _is_js_file(path: str) -> bool:
    return any(path.endswith(ext) for ext in (".js", ".ts", ".tsx"))


def _py_assert_is_weak(line: str) -> bool:
    """Return whether a Python assert statement only checks truthiness."""
    try:
        parsed = ast.parse(line.strip())
    except SyntaxError:
        return False

    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.Assert):
        return False

    test = parsed.body[0].test
    strong_comparisons = (
        ast.Eq, ast.NotEq, ast.Lt, ast.Gt, ast.LtE, ast.GtE, ast.In, ast.NotIn
    )
    if any(
        isinstance(node, ast.Compare)
        and any(isinstance(op, strong_comparisons) for op in node.ops)
        for node in ast.walk(test)
    ):
        return False
    return True


# ---------------------------------------------------------------------------
# Per-hunk rules
# ---------------------------------------------------------------------------

def _check_skip_added(df: DiffFile) -> list[Finding]:
    """Check for skip/xit/xdescribe patterns added."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""
    for hunk in df.hunks:
        for lineno, text in hunk.added:
            for pat in _SKIP_PATTERNS_ADDED:
                if pat.search(text):
                    # Make sure this wasn't also in a removed line (i.e. already present)
                    already = any(pat.search(rt) for _, rt in hunk.removed)
                    if not already:
                        findings.append(Finding(
                            rule="skip-added",
                            severity="high",
                            file=path,
                            line=lineno,
                            old=None,
                            new=text.strip(),
                            message="test skipped",
                        ))
                    break  # Don't double-report same line
    return findings


def _check_focus_added(df: DiffFile) -> list[Finding]:
    """Check for .only / fit / fdescribe added (info)."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""
    for hunk in df.hunks:
        for lineno, text in hunk.added:
            for pat in _FOCUS_PATTERNS:
                if pat.search(text):
                    already = any(pat.search(rt) for _, rt in hunk.removed)
                    if not already:
                        findings.append(Finding(
                            rule="focus-added",
                            severity="info",
                            file=path,
                            line=lineno,
                            old=None,
                            new=text.strip(),
                            message="focused test; remember to remove before merge",
                        ))
                    break
    return findings


def _check_suppression_added(df: DiffFile) -> list[Finding]:
    """Check for new lint/type suppressions."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""
    for hunk in df.hunks:
        for lineno, text in hunk.added:
            for pat in _SUPPRESSION_PATTERNS:
                if pat.search(text):
                    already = any(pat.search(rt) for _, rt in hunk.removed)
                    if not already:
                        findings.append(Finding(
                            rule="suppression-added",
                            severity="high",
                            file=path,
                            line=lineno,
                            old=None,
                            new=text.strip(),
                            message="lint/type suppression added in test file",
                        ))
                    break
    return findings


def _check_error_swallowed(df: DiffFile) -> list[Finding]:
    """Check for new empty except/catch blocks."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""
    for hunk in df.hunks:
        added_lines = [text for _, text in hunk.added]
        for i, (lineno, text) in enumerate(hunk.added):
            stripped = text.strip()
            # Python: except ...: pass  or bare except: (with nothing meaningful after)
            if re.match(r"except\s*.*:", stripped):
                # Check if the next added line is pass or empty
                rest = added_lines[i + 1:i + 3]
                if any(r.strip() == "pass" for r in rest) or not rest:
                    findings.append(Finding(
                        rule="error-swallowed",
                        severity="high",
                        file=path,
                        line=lineno,
                        old=None,
                        new=stripped,
                        message="exception swallowed in test",
                    ))
            # JS: empty catch block
            if re.match(r"}\s*catch\s*\(", stripped) or re.match(r"catch\s*\(", stripped):
                # Check if next line is just }
                rest = added_lines[i + 1:i + 3]
                if any(r.strip() == "}" for r in rest) or not rest:
                    findings.append(Finding(
                        rule="error-swallowed",
                        severity="high",
                        file=path,
                        line=lineno,
                        old=None,
                        new=stripped,
                        message="exception swallowed in test",
                    ))
    return findings


def _pair_lines(hunk: Hunk) -> list[tuple[tuple[int, str], tuple[int, str]]]:
    """Pair removed and added lines using SequenceMatcher, ratio >= 0.72."""
    pairs = []
    removed = list(hunk.removed)
    added = list(hunk.added)
    used_added: set[int] = set()

    for r_idx, (r_lineno, r_text) in enumerate(removed):
        best_ratio = 0.0
        best_a_idx = -1
        for a_idx, (a_lineno, a_text) in enumerate(added):
            if a_idx in used_added:
                continue
            ratio = difflib.SequenceMatcher(
                None, r_text.strip(), a_text.strip()
            ).ratio()
            if ratio < 0.72 and _looks_like_js_matcher_change(r_text, a_text):
                normalized_old = _normalize_js_matcher_line(r_text)
                normalized_new = _normalize_js_matcher_line(a_text)
                ratio = difflib.SequenceMatcher(
                    None, normalized_old, normalized_new
                ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_a_idx = a_idx
        if best_ratio >= 0.72 and best_a_idx >= 0:
            used_added.add(best_a_idx)
            pairs.append((removed[r_idx], added[best_a_idx]))
    return pairs


def _looks_like_js_matcher_change(old_text: str, new_text: str) -> bool:
    """Return whether two lines compare the same JS expression differently."""
    return (
        _is_js_file_for_line(old_text, new_text)
        and bool(_JS_MATCHER_RE.search(old_text))
        and bool(_JS_MATCHER_RE.search(new_text))
    )


def _is_js_file_for_line(old_text: str, new_text: str) -> bool:
    return "expect(" in old_text and "expect(" in new_text


def _normalize_js_matcher_line(text: str) -> str:
    return _JS_MATCHER_RE.sub(".MATCHER(", text.strip())


def _check_bound_loosened(df: DiffFile) -> list[Finding]:
    """Check for numeric bounds moved in the permissive direction."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""

    for hunk in df.hunks:
        pairs = _pair_lines(hunk)
        for (old_lineno, old_text), (new_lineno, new_text) in pairs:
            old_m = _BOUND_RE.search(old_text.strip())
            new_m = _BOUND_RE.search(new_text.strip())
            if _is_js_file(path):
                old_m_js = _JS_BOUND_RE.search(old_text.strip())
                new_m_js = _JS_BOUND_RE.search(new_text.strip())
                if not old_m_js or not new_m_js:
                    continue
                old_lhs = re.sub(r"\s+", " ", old_m_js.group(1)).strip()
                new_lhs = re.sub(r"\s+", " ", new_m_js.group(1)).strip()
                old_op = old_m_js.group(2)
                new_op = new_m_js.group(2)
                old_val = float(old_m_js.group(3))
                new_val = float(new_m_js.group(3))
                if old_lhs != new_lhs or old_op != new_op:
                    continue
                permissive = (
                    old_op in ("toBeLessThan", "toBeLessThanOrEqual")
                    and new_val > old_val
                ) or (
                    old_op in ("toBeGreaterThan", "toBeGreaterThanOrEqual")
                    and new_val < old_val
                )
                if permissive:
                    findings.append(Finding(
                        rule="bound-loosened",
                        severity="high",
                        file=path,
                        line=new_lineno,
                        old=old_text.strip(),
                        new=new_text.strip(),
                        message="same comparison, wider bound. CI can still be green.",
                    ))
                continue
            if not old_m or not new_m:
                continue

            old_lhs = re.sub(r"\s+", " ", old_m.group(1)).strip()
            new_lhs = re.sub(r"\s+", " ", new_m.group(1)).strip()
            old_op = old_m.group(2)
            new_op = new_m.group(2)
            try:
                old_val = float(old_m.group(3))
                new_val = float(new_m.group(3))
            except ValueError:
                continue

            # Operator must be the same
            if old_op != new_op:
                continue

            # LHS must match after whitespace collapse
            if old_lhs != new_lhs:
                continue

            # Same value is not a finding
            if old_val == new_val:
                continue

            # Determine if permissive
            permissive = False
            if old_op in ("<", "<="):
                # Upper bound grew -> permissive
                permissive = new_val > old_val
            elif old_op in (">", ">="):
                # Lower bound shrank -> permissive
                permissive = new_val < old_val

            if permissive:
                findings.append(Finding(
                    rule="bound-loosened",
                    severity="high",
                    file=path,
                    line=new_lineno,
                    old=old_text.strip(),
                    new=new_text.strip(),
                    message="same comparison, wider bound. CI can still be green.",
                ))
    return findings


def _check_matcher_downgrade(df: DiffFile) -> list[Finding]:
    """Check for strong->weak matcher downgrades."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""

    for hunk in df.hunks:
        pairs = _pair_lines(hunk)
        for (old_lineno, old_text), (new_lineno, new_text) in pairs:
            old_s = old_text.strip()
            new_s = new_text.strip()

            if _is_js_file(path):
                old_matchers = _JS_MATCHER_RE.findall(old_s)
                new_matchers = _JS_MATCHER_RE.findall(new_s)
                old_has_strong = any(m in _JS_STRONG for m in old_matchers)
                new_has_strong = any(m in _JS_STRONG for m in new_matchers)
                new_has_weak = any(m in _JS_WEAK for m in new_matchers)
                if old_has_strong and not new_has_strong and new_has_weak:
                    findings.append(Finding(
                        rule="matcher-downgrade",
                        severity="high",
                        file=path,
                        line=new_lineno,
                        old=old_s,
                        new=new_s,
                        message="strong matcher replaced with weak check",
                    ))
            elif _is_py_file(path):
                old_has_strong = bool(_PY_STRONG_LINE_RE.search(old_s))
                new_has_strong = bool(_PY_STRONG_LINE_RE.search(new_s))
                new_has_weak = bool(_PY_WEAK_LINE_RE.search(new_s))
                if not new_has_weak:
                    new_has_weak = _py_assert_is_weak(new_s)
                if old_has_strong and new_has_strong and _is_length_only_rewrite(
                    old_s, new_s
                ):
                    findings.append(Finding(
                        rule="matcher-downgrade",
                        severity="high",
                        file=path,
                        line=new_lineno,
                        old=old_s,
                        new=new_s,
                        message="collection equality replaced with a length-only check",
                    ))
                    continue
                if old_has_strong and not new_has_strong and new_has_weak:
                    findings.append(Finding(
                        rule="matcher-downgrade",
                        severity="high",
                        file=path,
                        line=new_lineno,
                        old=old_s,
                        new=new_s,
                        message="strong matcher replaced with weak check",
                    ))
    return findings


def _is_length_only_rewrite(old_text: str, new_text: str) -> bool:
    """Return whether collection equality became a length-only comparison."""
    try:
        old_tree = ast.parse(old_text.strip())
        new_tree = ast.parse(new_text.strip())
    except SyntaxError:
        return False
    if len(old_tree.body) != 1 or len(new_tree.body) != 1:
        return False
    old_stmt = old_tree.body[0]
    new_stmt = new_tree.body[0]
    if not isinstance(old_stmt, ast.Assert) or not isinstance(new_stmt, ast.Assert):
        return False
    if not isinstance(old_stmt.test, ast.Compare) or not isinstance(new_stmt.test, ast.Compare):
        return False
    if len(old_stmt.test.ops) != 1 or len(new_stmt.test.ops) != 1:
        return False
    if not isinstance(old_stmt.test.ops[0], ast.Eq) or not isinstance(new_stmt.test.ops[0], ast.Eq):
        return False
    old_left = old_stmt.test.left
    new_left = new_stmt.test.left
    return (
        not (isinstance(old_left, ast.Call)
             and isinstance(old_left.func, ast.Name)
             and old_left.func.id == "len")
        and isinstance(new_left, ast.Call)
        and isinstance(new_left.func, ast.Name)
        and new_left.func.id == "len"
    )


def _check_retarget(df: DiffFile) -> list[Finding]:
    """Check for retarget: same matcher, different literal (info)."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""

    for hunk in df.hunks:
        pairs = _pair_lines(hunk)
        for (old_lineno, old_text), (new_lineno, new_text) in pairs:
            old_s = old_text.strip()
            new_s = new_text.strip()

            if _is_js_file(path):
                old_matchers = _JS_MATCHER_RE.findall(old_s)
                new_matchers = _JS_MATCHER_RE.findall(new_s)
                # Same strong matcher, different text -> info
                if old_matchers and new_matchers:
                    if (old_matchers == new_matchers
                            and all(m in _JS_STRONG for m in old_matchers)
                            and old_s != new_s):
                        findings.append(Finding(
                            rule="retarget",
                            severity="info",
                            file=path,
                            line=new_lineno,
                            old=old_s,
                            new=new_s,
                            message="expected value changed, matcher unchanged",
                        ))
            elif _is_py_file(path):
                # assertEqual(x, old) -> assertEqual(x, new)
                old_has_strong = bool(_PY_STRONG_LINE_RE.search(old_s))
                new_has_strong = bool(_PY_STRONG_LINE_RE.search(new_s))
                if old_has_strong and new_has_strong and old_s != new_s:
                    # Check it's not a bound-loosened case (has comparison operator)
                    old_bound = _BOUND_RE.search(old_s)
                    new_bound = _BOUND_RE.search(new_s)
                    if old_bound and new_bound:
                        # This is handled by bound-loosened
                        continue
                    findings.append(Finding(
                        rule="retarget",
                        severity="info",
                        file=path,
                        line=new_lineno,
                        old=old_s,
                        new=new_s,
                        message="expected value changed, matcher unchanged",
                    ))
    return findings


# ---------------------------------------------------------------------------
# Per-file rules (need full old/new text)
# ---------------------------------------------------------------------------

def _count_py_assertions(source: str) -> dict[str, int]:
    """Parse Python source and count assertions per test function.

    Returns {func_name: count}.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    counts: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                count = 0
                for child in ast.walk(node):
                    if isinstance(child, ast.Assert):
                        count += 1
                    elif isinstance(child, ast.Call):
                        func = child.func
                        name = ""
                        if isinstance(func, ast.Attribute):
                            name = func.attr
                        elif isinstance(func, ast.Name):
                            name = func.id
                        if name in _PY_ASSERT_METHODS:
                            count += 1
                counts[node.name] = count
    return counts


def _py_test_linenos(source: str) -> dict[str, int]:
    """Return definition line numbers for Python test functions."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    return {
        node.name: node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def _count_js_assertions(source: str) -> dict[str, int]:
    """Count assertion lines per test block in JS/TS source.

    Uses indentation-based heuristic.
    Returns {test_name_or_index: count}.
    """
    lines = source.replace("\r\n", "\n").split("\n")
    tests: list[tuple[str, int, int, int]] = []  # (name, start_line, indent, count)

    for i, line in enumerate(lines):
        m = _JS_TEST_START.match(line)
        if m:
            indent = len(line) - len(line.lstrip())
            # Extract test name
            name_m = re.search(r"(?:it|test)(?:\.only|\.skip)?\s*\(\s*['\"]([^'\"]*)['\"]", line)
            name = name_m.group(1) if name_m else f"__test_{i}"
            tests.append((name, i, indent, 0))

    counts: dict[str, int] = {}
    for idx, (name, start, indent, _) in enumerate(tests):
        # Block extends to next test at same or lower indentation, or end of file
        end = len(lines)
        for next_idx in range(idx + 1, len(tests)):
            next_name, next_start, next_indent, _ = tests[next_idx]
            if next_indent <= indent:
                end = next_start
                break
        count = 0
        for j in range(start, end):
            if _JS_ASSERTION_RE.search(lines[j]):
                count += 1
        counts[name] = count
    return counts


def _reconstruct_file_text(df: DiffFile, *, old: bool) -> Optional[str]:
    """Reconstruct a complete file when a direct file read is unavailable."""
    if not df.hunks:
        return None
    lines: list[str] = []
    for hunk in df.hunks:
        removed = {line: text for line, text in hunk.removed}
        added = {line: text for line, text in hunk.added}
        context = {line: text for line, text in hunk.context}
        source_lines = removed if old else added
        source_lines = {**context, **source_lines}
        start = hunk.old_start if old else hunk.new_start
        count = hunk.old_count if old else hunk.new_count
        for line_number in range(start, start + count):
            if line_number in source_lines:
                lines.append(source_lines[line_number])
    return "\n".join(lines)


def _check_test_removed(df: DiffFile, old_text: Optional[str],
                        new_text: Optional[str]) -> list[Finding]:
    """Check for test functions/blocks that disappeared."""
    findings: list[Finding] = []
    path = df.old_path or df.new_path or ""

    # Whole file deleted
    if df.is_deleted:
        findings.append(Finding(
            rule="test-removed",
            severity="high",
            file=path,
            line=None,
            old=None,
            new=None,
            message="test file deleted",
        ))
        return findings

    if old_text is None or new_text is None:
        return findings

    if _is_py_file(path):
        old_counts = _count_py_assertions(old_text)
        new_counts = _count_py_assertions(new_text)
        for name in old_counts:
            if name not in new_counts:
                findings.append(Finding(
                    rule="test-removed",
                    severity="high",
                    file=df.new_path or path,
                    line=None,
                    old=f"def {name}",
                    new=None,
                    message=f"test function '{name}' removed",
                ))
    elif _is_js_file(path):
        old_counts = _count_js_assertions(old_text)
        new_counts = _count_js_assertions(new_text)
        for name in old_counts:
            if name not in new_counts:
                findings.append(Finding(
                    rule="test-removed",
                    severity="high",
                    file=df.new_path or path,
                    line=None,
                    old=name,
                    new=None,
                    message=f"test '{name}' removed",
                ))
    return findings


def _check_assertion_removed(df: DiffFile, old_text: Optional[str],
                             new_text: Optional[str]) -> list[Finding]:
    """Check for surviving tests that lost assertions."""
    findings: list[Finding] = []
    path = df.new_path or df.old_path or ""

    if df.is_deleted or old_text is None or new_text is None:
        return findings

    if _is_py_file(path):
        old_counts = _count_py_assertions(old_text)
        new_counts = _count_py_assertions(new_text)
        new_linenos = _py_test_linenos(new_text)
        for name in old_counts:
            if name in new_counts:
                if new_counts[name] < old_counts[name]:
                    findings.append(Finding(
                        rule="assertion-removed",
                        severity="high",
                        file=path,
                        line=new_linenos.get(name),
                        old=_assertion_count_text(old_counts[name]),
                        new=_assertion_count_text(new_counts[name]),
                        message=f"test '{name}' lost an assertion",
                    ))
    elif _is_js_file(path):
        old_counts = _count_js_assertions(old_text)
        new_counts = _count_js_assertions(new_text)
        for name in old_counts:
            if name in new_counts:
                if new_counts[name] < old_counts[name]:
                    findings.append(Finding(
                        rule="assertion-removed",
                        severity="high",
                        file=path,
                        line=None,
                        old=_assertion_count_text(old_counts[name]),
                        new=_assertion_count_text(new_counts[name]),
                        message=f"test '{name}' lost an assertion",
                    ))
    return findings


def _assertion_count_text(count: int) -> str:
    """Format an assertion count with correct singular/plural grammar."""
    noun = "assertion" if count == 1 else "assertions"
    return f"{count} {noun}"


def _check_weak_new_test(df: DiffFile, new_text: Optional[str]) -> list[Finding]:
    """Check for new test files/functions with only weak oracles."""
    findings: list[Finding] = []
    path = df.new_path or ""

    added_test_names = {
        match.group(1)
        for hunk in df.hunks
        for _, text in hunk.added
        for match in [re.match(r"\s*(?:async\s+)?def\s+(test_\w+)\s*\(", text)]
        if match
    }
    if not df.is_new and not added_test_names:
        return findings

    if new_text is None:
        # Try to reconstruct from diff added lines for new files
        if df.hunks:
            new_text = "\n".join(text for hunk in df.hunks for _, text in hunk.added)
        else:
            return findings

    if _is_py_file(path):
        try:
            tree = ast.parse(new_text)
        except SyntaxError:
            return findings

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_") and (
                    df.is_new or node.name in added_test_names
                ):
                    has_strong = False
                    has_any_assertion = False
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assert):
                            has_any_assertion = True
                            # Check if it's a strong assert
                            test_node = child.test
                            if isinstance(test_node, ast.Compare):
                                for op in test_node.ops:
                                    if isinstance(op, (ast.Eq, ast.NotEq, ast.Lt,
                                                       ast.LtE, ast.Gt, ast.GtE,
                                                       ast.In, ast.NotIn)):
                                        has_strong = True
                            elif isinstance(test_node, ast.Call):
                                # Could be a function call, check name
                                pass
                        elif isinstance(child, ast.Call):
                            func = child.func
                            name = ""
                            if isinstance(func, ast.Attribute):
                                name = func.attr
                            elif isinstance(func, ast.Name):
                                name = func.id
                            if name in _PY_ASSERT_METHODS:
                                has_any_assertion = True
                                if name in _PY_STRONG_METHODS:
                                    has_strong = True
                    if not has_strong:
                        findings.append(Finding(
                            rule="weak-new-test",
                            severity="high",
                            file=path,
                            line=None,
                            old=None,
                            new=None,
                            message=f"new test '{node.name}' has no strong oracle",
                        ))

    elif _is_js_file(path):
        # Check all test blocks in the new file
        counts = _count_js_assertions(new_text)
        lines = new_text.replace("\r\n", "\n").split("\n")
        for i, line in enumerate(lines):
            m = _JS_TEST_START.match(line)
            if m:
                indent = len(line) - len(line.lstrip())
                # Find block end
                end = len(lines)
                for j in range(i + 1, len(lines)):
                    m2 = _JS_TEST_START.match(lines[j])
                    if m2:
                        j_indent = len(lines[j]) - len(lines[j].lstrip())
                        if j_indent <= indent:
                            end = j
                            break
                # Check if any strong matcher exists
                has_strong = False
                for j in range(i, end):
                    matchers = _JS_MATCHER_RE.findall(lines[j])
                    if any(m in _JS_STRONG for m in matchers):
                        has_strong = True
                        break
                    # assert. or assert( are strong if they have comparison
                    if re.search(r"assert\.(equal|strictEqual|deepEqual|deepStrictEqual|throws)", lines[j]):
                        has_strong = True
                        break
                if not has_strong:
                    name_m = re.search(r"(?:it|test)(?:\.only|\.skip)?\s*\(\s*['\"]([^'\"]*)['\"]", line)
                    name = name_m.group(1) if name_m else f"test at line {i+1}"
                    findings.append(Finding(
                        rule="weak-new-test",
                        severity="high",
                        file=path,
                        line=None,
                        old=None,
                        new=None,
                        message=f"new test '{name}' has no strong oracle",
                    ))

    return findings


# ---------------------------------------------------------------------------
# Main entry: run all rules on a file
# ---------------------------------------------------------------------------

def analyze_file(df: DiffFile, old_text: Optional[str] = None,
                 new_text: Optional[str] = None) -> list[Finding]:
    """Run all rules on one DiffFile, return sorted findings."""
    findings: list[Finding] = []

    # Hunk-level rules
    findings.extend(_check_skip_added(df))
    findings.extend(_check_focus_added(df))
    findings.extend(_check_suppression_added(df))
    findings.extend(_check_error_swallowed(df))
    findings.extend(_check_bound_loosened(df))
    findings.extend(_check_matcher_downgrade(df))
    findings.extend(_check_retarget(df))

    if old_text is None:
        old_text = _reconstruct_file_text(df, old=True)
    if new_text is None:
        new_text = _reconstruct_file_text(df, old=False)

    # File-level rules
    findings.extend(_check_test_removed(df, old_text, new_text))
    findings.extend(_check_assertion_removed(df, old_text, new_text))

    # For new files, try to get new_text from hunks if not provided
    effective_new = new_text
    if df.is_new and effective_new is None and df.hunks:
        effective_new = "\n".join(text for hunk in df.hunks for _, text in hunk.added)
    findings.extend(_check_weak_new_test(df, effective_new))

    # Sort by file, line, rule
    findings.sort(key=lambda f: (
        f.file,
        f.line if f.line is not None else 0,
        f.rule,
    ))

    return findings
