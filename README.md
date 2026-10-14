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
# or
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

tamperproof blocks edits during a Claude session. This reads the diff afterwards, for any agent, and allows a real test update.
i-dont-believe-you counts assertions and looks for skips. It misses a same-count rewrite and a permissive bound. Those two are the point of this tool.
RepoPilot is a broad deterministic reviewer. This does one job and fits on one screen.
receipts re-runs the suite with the fix reverted. Use it when you need proof. This is the instant pass.

## Star

Star it if a green diff ever changed `< 200` to `< 500` and the assertion count stayed the same.
