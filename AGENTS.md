# AGENTS.md

Copy this file into the new repository as `AGENTS.md` before writing code.

The name is locked: **goalpost**. Command, import package, and GitHub repo are all `goalpost`. Do not rename it.

GitHub About line, exact:

> See where a diff made the tests easier to pass. Local, no API key.

`goalpost` does not say "tests." The About line and the first README sentence must. That is how this name still gets clicked.

Before the first PyPI upload, check that the name `goalpost` is free. If it is taken, keep the command as `goalpost` and stop for the human. Do not silently publish under another name.

This repository is a small local CLI. It is not an AI app, not an agent skill, and not a general code reviewer.

## Goal

Ship v0.1 of `goalpost`: a local command a stranger can run on a git diff and trust when it says a check got weaker.

The goal is a correct, narrow tool with a README whose first screen is the `< 200` to `< 500` demo. It is not a platform, a Claude plugin, or a general reviewer. Stars come from that demo being real. Do not add features to chase them.

You are finished only when the definition of done at the bottom of this file is true. If a step here conflicts with a cleverer design, follow this file.

## What this project is

`goalpost` reads a git diff and reports where the checks got easier to pass.

A coding agent can leave CI green by editing the grader instead of the bug: skip a test, delete an assertion, swap `toEqual` for `toBeTruthy`, or move `assert latency < 200` to `assert latency < 500`. A new test file can also be empty of any real oracle (`assert result is not None`, or no assert at all). This tool surfaces those lines.

It is a review signal, not an accusation. Changing `toBe(200)` to `toBe(201)` is an equally strict retarget. That is **info**, not a failure. The product exists because counting the word `assert` misses the interesting cases, and because forbidding every test edit is the wrong rule.

No model. No API key. Nothing leaves the machine. The same diff always produces the same report.

### Who it is for

Developers who merge or skim agent-written diffs and no longer trust a green check by itself. They use Claude Code, Codex, Cursor, Copilot, or similar, and they review the result. Secondary reader: the same person, at the end of their own agent session, before they commit.

Not the audience: security teams wanting a SAST product, data scientists, or people looking for a Claude skill that changes the agent's tone.

### The one-sentence promise

For a developer reviewing an agent diff, this tool turns "CI is green" into a short list of weakened checks, without a model, an API key, or a test run.

## What you should build

v0.1 is a Python 3.11 command-line tool managed with `uv`.

```
goalpost                         # git diff HEAD (staged + unstaged)
goalpost --base origin/main      # branch vs base
goalpost --json                  # stable JSON on stdout
goalpost demo                    # runs against built-in fixtures, no repo required
```

Exit codes:

- `0` — no high finding
- `1` — at least one high finding
- `2` — git missing, not a repo, or the diff cannot be read

Human output is plain text. No required TUI. `rich` is forbidden in v0.1 so the report stays diffable in tests.

Stack is stdlib plus `pytest`: `subprocess` to call `git`, string parsing of the unified diff, `difflib` to pair removed and added lines. Use `ast` only when a full new Python test file is available on disk. Do not add tree-sitter, Semgrep, or an LLM client.

### High findings

Each finding includes rule id, file, line, old line, new line, and one sentence a reviewer can trust.

| Rule id | Fire when |
|---|---|
| `skip-added` | `.skip`, `xit`, `xdescribe`, `@pytest.mark.skip`, `@unittest.skip`, `pytest.skip(` added on a test |
| `test-removed` | A test file matching the test globs is deleted, or a `def test_*` / `it(` / `test(` name disappears |
| `assertion-removed` | A surviving test loses an assertion. Count **per test**, not per file |
| `matcher-downgrade` | Equality becomes truthiness: `toEqual` / `toBe` / `toStrictEqual` / `assertEqual` / `==` rewritten to `toBeTruthy` / `toBeDefined` / `toBeFalsy` / `assertIsNotNone` / `assert x` / bare truthiness |
| `bound-loosened` | Same operator, same left side, numeric bound moved in the permissive direction. `< 200` to `< 500` is high. `> 900` to `> 500` is high. Do not fire if the operator changed |
| `error-swallowed` | New empty `except`, `except ...: pass`, or empty `catch` in a test file |
| `suppression-added` | New `# noqa`, `# type: ignore`, `# pragma: no cover`, `@ts-ignore`, `@ts-expect-error`, `eslint-disable` |
| `weak-new-test` | A new test file or new test function whose only oracle is "did not crash", not-None, or truthiness |

### Info, never a failing exit

- Expected literal changed but the matcher stayed equally strict (`toBe(5)` to `toBe(6)`, `status == 200` to `status == 201`).
- `.only` / `fit` / `fdescribe` added. Print it. Do not fail the process in v0.1.

### Languages in v0.1

Python (`pytest`, `unittest`) and JavaScript/TypeScript (`node:test`, Jest, Vitest). Detection is on the diff text. Do not typecheck the project. Do not execute tests.

Test-file globs to start from: `test_*.py`, `*_test.py`, `tests/**/*.py`, `*.test.js`, `*.test.ts`, `*.test.tsx`, `*.spec.js`, `*.spec.ts`, `*.spec.tsx`, `**/__tests__/**`.

### Fixture gate, before the CLI exists

Write at least 30 labeled diffs first, half true weakenings and half legitimate edits. High-severity precision on that set must be at least 90% before any README claim, demo, or publish.

These five cases are the contract. Get them right before anything else:

1. `assert latency < 200` replaced by `assert latency < 500` is **high** `bound-loosened`. A script that only counts assertion lines stays silent. That silence is the demo.
2. `expect(user.id).toEqual(7)` replaced by `expect(user.id).toBeTruthy()` is **high** `matcher-downgrade`.
3. `expect(status).toBe(200)` replaced by `expect(status).toBe(201)` is **info**, not high.
4. A deleted `it.skip(...)` is not a finding.
5. A new `test_retry.py` that only contains `assert result is not None` is **high** `weak-new-test`.

Also cover: formatting-only diff, renamed local, new strong assertion added, assertion removed in one test while another test in the same file gains one, string that merely contains the word `assert`.

If you cannot label the bound and matcher cases consistently, ship only `skip-added`, `test-removed`, `assertion-removed`, `error-swallowed`, `suppression-added`, and `weak-new-test`. Do not fake the bound rule.

### Do not build in v0.1

- A model, a prompt, or an API call
- Running pytest, jest, or vitest
- A hook that blocks the agent from editing tests
- An MCP server, GitHub App, or published Action
- SARIF, auto-fix, a rule DSL, or a config file
- Go, Rust, Java, C#, PHP, RSpec, or "any language"
- Security taint, blast radius, secrets, or general code quality
- A web UI
- Emoji in the report or the README

A sample GitHub Actions snippet may appear in the README only. Do not create a Marketplace action.

## Use cases the README and the tests must show

Write these as stories, not as features.

1. **Before you commit an agent session.** The suite is green. You run the tool on the working tree. It prints that the agent skipped `resets the backoff` or widened a threshold. You revert that hunk and keep the real fix.
2. **Reviewing an agent PR you did not watch.** `goalpost --base origin/main` on a large diff. You read the high findings first, then the files they point at, instead of scrolling two thousand lines hoping to notice a weaker expect.
3. **The new test does not pin anything.** The agent added a test file because you asked for tests. The file calls the function and asserts the result is not `None`. The tool flags it. This is the common case; do not imply that blatant cheating is common.
4. **You already have a grep, and it is not enough.** Show the latency hunk next to an assertion-count one-liner that prints nothing. This is the 30-second demo. It is the reason the tool exists.
5. **A later CI gate, same command.** `--json` and exit code `1` are enough for a workflow the user pastes themselves. Do not build the integration.

Out of scope, and say so in the README so users do not file these as bugs:

- Proving a test would fail if the production fix was reverted. That is a different tool (receipts). Link it. Do not reimplement it.
- Stopping the agent mid-session from touching tests. That is tamperproof, and it is the wrong default because many test edits are legitimate.
- Telling the user the production change is correct.

## How this should talk about neighbors

Do not claim there is no other tool. Do not write a long competitor matrix above the fold. Lower in the README, four sentences:

- tamperproof blocks edits during a Claude session. This reads the diff afterwards, for any agent, and allows a real test update.
- i-dont-believe-you counts assertions and looks for skips. It misses a same-count rewrite and a permissive bound. Those two are the point of this tool.
- RepoPilot is a broad deterministic reviewer. This does one job and fits on one screen.
- receipts re-runs the suite with the fix reverted. Use it when you need proof. This is the instant pass.

## Name

Locked to `goalpost`. Do not revisit other names, and do not rename the command.

`goalpost` will not explain itself in a trending list. Compensate only on the public surface:

- The About line is `See where a diff made the tests easier to pass. Local, no API key.`
- README line 1 contains the word "test."
- The first code block stays the `< 200` to `< 500` diff. That screenshot is the star, not the name.

Do not put this history in `README.md`.

## README to ship

Write `README.md` from the template below. Do not add a badge wall, an architecture diagram, a "why I built this" origin story, or the words "AI-powered." The first screen must contain the pain sentence, the hero diff, both outputs, and the install command. A reader should understand the tool without scrolling on a laptop.

Keep the Star line. It is a specific moment, not "please star." That pattern is what people actually share.

```markdown
# goalpost

A diff can stay green by making the test easier.

`goalpost` reads `git diff` and prints the lines where a check got weaker:
a bound moved from `< 200` to `< 500`, `toEqual` became `toBeTruthy`,
a test was skipped, or a new test asserts nothing but "not None."

No model. No API key. Nothing leaves the machine.

## The grep does not catch this

```diff
- assert latency < 200
+ assert latency < 500
```

An assertion-count script stays silent. One assert left, one assert arrived.

```text
$ git diff -U0 | grep -c '^-.*assert'    # 1
$ git diff -U0 | grep -c '^+.*assert'    # 1
```

```text
$ goalpost
high  bound-loosened  tests/test_latency.py:12
  - assert latency < 200
  + assert latency < 500
  same comparison, wider bound. CI can still be green.

1 high. Exit 1.
```

`toBe(200)` rewritten as `toBe(201)` is not a failure. The bar stayed as strict.
That line is printed as info so you can glance at it.

## Install

Requires Git and Python 3.11+.

```bash
uvx goalpost
```

Or, from a checkout:

```bash
uv run goalpost
```

No repository handy:

```bash
uvx goalpost demo
```

## Use it

End of an agent session, before you commit:

```bash
goalpost
```

A branch you are about to merge:

```bash
goalpost --base origin/main
```

## What it flags

| | Example | Result |
|---|---|---|
| Bound loosened | `< 200` to `< 500` | high |
| Matcher downgraded | `toEqual(id)` to `toBeTruthy()` | high |
| Test skipped or deleted | `it(...)` to `it.skip(...)` | high |
| Assertion removed inside a test that remains | one `expect` deleted, test name kept | high |
| New test with no real oracle | `assert result is not None` only | high |
| Error swallowed, or a new lint suppression | `except: pass`, `# type: ignore` | high |
| Expected value retargeted, matcher unchanged | `toBe(200)` to `toBe(201)` | info |

Python (`pytest`, `unittest`) and JS/TS (`Jest`, `Vitest`, `node:test`) in v0.1.

## Three situations

1. The agent said the tests passed. You run this before committing and see it skipped the test it could not fix.
2. You are reviewing someone else's agent PR. You read the high findings, then those files, instead of the whole diff.
3. You asked for tests and got a new file that only checks the result is not `None`.

## What this will not do

It does not run your suite, and it does not prove the tests would fail without the fix.
It does not block an agent from editing tests. Legitimate edits are normal.
It does not know whether the production change is right.
It misses tricks that need a full compile: a helper moved to another file, a component unmounted before the assert, a mock that swallows the call. Silence is not a clean bill.

## Star

Star it if a green diff ever changed `< 200` to `< 500` and the assertion count stayed the same.
```

### README rules that are about stars, not taste

- The title and the About line repeat the pain in ordinary words. Do not lead with "Python CLI", "unified diff parser", or "static analysis."
- The hero example is the case a famous one-liner misses. That contrast is the share. Do not swap it for a generic `it.skip` example. Skipping a test is obvious; a wider bound is the screenshot.
- Install stays a single command, above any flag documentation.
- The catch-table stays at seven rows. Do not add a row for every rule id.
- Non-goals stay. Hacker News trusts a tool that says what it misses. Agents also file fewer junk issues.
- No emoji, no "blazing fast", no star-count badges, no "the only tool that."
- After the tool runs on a real public diff you are allowed to use, add one real screenshot or asciinema under the hero. Do not fake output. Until then, the fenced text above is the demo.
- The Star sentence names a moment the reader has had. Do not write "If you find this useful, consider starring."

## How to build it

Follow this. Do not introduce a plugin system, a config file, or a second package.

### Layout

```
pyproject.toml          # requires-python >= 3.11, no runtime dependencies
LICENSE                 # MIT
README.md
src/goalpost/__init__.py
src/goalpost/cli.py      # argparse, exit codes, text and JSON
src/goalpost/gitdiff.py  # run git, parse a unified diff
src/goalpost/rules.py    # pure functions from old text + new text + diff to findings
src/goalpost/report.py   # text and JSON renderers
tests/fixtures/         # one input diff or file pair per case, plus expected findings
tests/test_contract.py
tests/PRECISION.md
```

Console script: `goalpost = "goalpost.cli:main"`.

### Pipeline

1. `argparse` only. Subcommand `demo`, flags `--base REF` and `--json`. No other flags in v0.1.
2. `demo` feeds the built-in latency fixture through the same rule functions as a real diff. It does not call git. It prints the high finding from the README and exits 1.
3. Otherwise call git with an argument list. Never `shell=True`. Never the network.
   - No flags: `git diff --no-color --unified=3 HEAD`
   - `--base REF`: `git diff --no-color --unified=3 REF...HEAD` (three dots). If `REF` does not resolve, exit 2 with the git error on stderr.
   - Not a repository, or git missing: exit 2.
4. Parse the unified diff into files, hunks, and whether the file was deleted. Ignore binary diffs.
5. Keep test paths only. Every rule in v0.1 applies only to test files. A `# type: ignore` in production code is not a finding.
6. For each changed test file that still exists, also load the full old text with `git show <rev>:path` and the full new text from the worktree. `assertion-removed` and `weak-new-test` need the full files. Hunk text alone is not enough. If `git show` cannot produce the old file, skip the per-test count for that file and do not guess.
7. Run the rules. Sort findings by file, then line, then rule id.
8. Empty diff or no findings: print `0 high.` and exit 0. Do not print a banner.

### What an assertion is

Closed lists. Do not "detect assertions" with a single regex for the word `assert`.

- Python: an `ast.Assert`, or a call whose function name is `assertEqual`, `assertNotEqual`, `assertTrue`, `assertFalse`, `assertIs`, `assertIsNot`, `assertIsNone`, `assertIsNotNone`, `assertIn`, `assertNotIn`, `assertRaises`, `assertAlmostEqual`, `assertGreater`, `assertLess`, `assertGreaterEqual`, `assertLessEqual`, `assertRegex`.
- JS/TS: a line containing `expect(` or `assert.` or `assert(`.

Strong oracles: `toEqual`, `toStrictEqual`, `toBe` (unless `toBeTruthy`, `toBeFalsy`, `toBeDefined`, `toBeUndefined`, `toBeNull`, `toBeNaN`), `assertEqual`, `assertNotEqual`, `==`, `!=`, and the numeric comparisons.
Weak oracles: `toBeTruthy`, `toBeFalsy`, `toBeDefined`, `toBeUndefined`, `toBeNull`, `assertIsNotNone`, `assertIsNone`, `assertTrue`, `assertFalse`, `assert x`, `assert result`, `is not None`, `is None`.

`matcher-downgrade` fires only when a paired line loses a strong oracle and the new line has a weak oracle and no strong oracle left.

### Per-test counts

- Python: parse old and new with `ast`. A test is a `FunctionDef` or `AsyncFunctionDef` whose name starts with `test_`. Count assertions inside that function only. Same name, fewer assertions, function still exists: one `assertion-removed`. Function gone: `test-removed`, not `assertion-removed`.
- JS/TS: do not add a JS parser. A test starts at a line matching `it(`, `test(`, `it.only(`, `test.only(`, `it.skip(`, `test.skip(`. The block runs to the next test at the same indentation or the end of the file. Count assertion lines in that span. If indentation is ambiguous, do not emit `assertion-removed` for that file.

Prefer a missed finding over a wrong one.

### Bounds

Inside a hunk, pair removed and added lines with `difflib.SequenceMatcher`. Consider a pair only when the ratio is at least `0.72`. On a pair:

- Operator must be the same token, one of `<`, `>`, `<=`, `>=`.
- The text to the left of the operator must match after whitespace is collapsed.
- The right side must be a single number.
- Permissive means the new number accepts more values: `<` and `<=` grew, `>` and `>=` shrank.
- If the operator changed, do not emit `bound-loosened`.

### Output contract

Text, one finding per block, matching the README:

```text
high  bound-loosened  tests/test_latency.py:12
  - assert latency < 200
  + assert latency < 500
  same comparison, wider bound. CI can still be green.

1 high. Exit 1.
```

Info uses the prefix `info ` and does not change the exit code. Exit code is about high findings only. The `Exit N` line is part of the text report.

JSON on stdout when `--json` is set. No other keys.

```json
{
  "high": [
    {
      "rule": "bound-loosened",
      "file": "tests/test_latency.py",
      "line": 12,
      "old": "assert latency < 200",
      "new": "assert latency < 500",
      "message": "same comparison, wider bound"
    }
  ],
  "info": [],
  "counts": { "high": 1, "info": 0 }
}
```

A deletion has `"new": null`. An addition has `"old": null`.

### Tests

Each contract case is a fixture with an expected rule id, or an expected absence. Tests call the rule functions directly. They do not need a git binary except one test that the CLI returns 2 outside a repository.

`tests/PRECISION.md` is three numbers you counted from the fixture set: high findings expected, high findings emitted, precision. Update it in the same change as the fixtures. Do not round up.

## Build order

1. Fixtures and expected findings. No CLI.
2. Diff parser and test-file classification.
3. High rules, precision gate.
4. Flags, exit codes, JSON, `demo`.
5. README from the template.
6. Run the tool on a real local repo you can explain. Do not claim you did if you did not.

## Implementation traps

- Do not treat the word `assert` inside a string or a comment as an assertion.
- Pair removed and added lines before deciding a bound moved. A big hunk can attach the wrong neighbors.
- Only call a bound loosened when the operator is unchanged.
- A pure reformat is not a finding.
- Windows newlines must not create phantom lines.
- Never `eval` a hunk. Never send the diff anywhere.
- Keep regexes boring. A catastrophic pattern is a bug, not a feature.
- If a user asks for another language, ask for a failing fixture. Do not add the language in the same change as a new rule.

## Definition of done

- `uv run pytest` passes offline.
- The five contract cases above behave exactly as specified.
- High-severity precision on the fixture set is at least 90%, and the file `tests/PRECISION.md` records the count.
- `uv run goalpost demo` prints at least the latency finding and exits 1.
- `README.md` matches the template and contains no unimplemented feature.
- You can explain the line-pairing and bound logic without the coding agent in the room.
