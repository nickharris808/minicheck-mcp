# minicheck-mcp

[![install](https://img.shields.io/badge/install-from%20GitHub-blue)](https://github.com/nickharris808/minicheck-mcp#install)
[![CI](https://img.shields.io/badge/ci-passing-brightgreen)](https://github.com/nickharris808/minicheck-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-83%20passing-brightgreen)](tests/)
[![python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![mcp](https://img.shields.io/badge/MCP-server-blueviolet)

**A model checker as an MCP server. Let the agent verify the state machine instead of guessing.**

## Why this exists

Agents design state machines constantly — retry loops, lock protocols, session lifecycles, hand-off
between sub-agents — and then reason about correctness in prose. Prose reasoning about concurrency
fails the same way for a model as it does for a person: by considering the interleavings that come to
mind and missing the one that doesn't.

An agent with a decision procedure does not have to guess. It gets a verdict and, when the property
fails, the exact sequence of steps that breaks it — which is also the thing it needs in order to fix
the design rather than apologise for it.

Agents write state machines all day — retry logic, lock protocols, session lifecycles, tool-call
graphs, hand-off between sub-agents. Then they reason about correctness *in prose*, and get it wrong
the way humans do: by missing an interleaving.

This gives the agent a decision procedure. It takes a **declarative spec — data, never code, so
nothing the agent sends is executed** — and returns a verdict with a shortest counterexample trace.

## Install

```
# from GitHub (PyPI release pending)
pip install "minicheck-mcp @ git+https://github.com/nickharris808/minicheck-mcp.git"
pip install "minicheck-mcp[mcp] @ git+https://github.com/nickharris808/minicheck-mcp.git"  # + the MCP SDK
```

> `pip install minicheck-mcp` will work once the PyPI release lands. The distribution is built and `twine check`-clean; publication is pending.

Then register it (`claude_desktop_config.json`, or any MCP client):

```json
{ "mcpServers": { "minicheck": { "command": "minicheck-mcp" } } }
```

The repo ships this as `mcp.json`.

## 30-second quickstart

Ask the agent: *"I have a retry loop that increments a counter until it succeeds. Check that it can't
retry more than 3 times."* It calls `check_invariant` and gets back:

```json
{
  "ok": true,
  "invariants": {
    "bounded_retries": {
      "holds": false,
      "steps": 4,
      "counterexample": [
        {"label": null,      "state": {"tries": 0, "done": 0}},
        {"label": "attempt", "state": {"tries": 1, "done": 0}},
        {"label": "attempt", "state": {"tries": 2, "done": 0}},
        {"label": "attempt", "state": {"tries": 3, "done": 0}},
        {"label": "attempt", "state": {"tries": 4, "done": 0}}
      ]
    }
  }
}
```

Not "this might loop forever" — the exact four steps that break it.

## Tools

| Tool | What it does |
|---|---|
| `check_invariant` | Exhaustive reachability. Shortest counterexample when a property fails. |
| `check_liveness` | Every reachable state can **still** reach the goal (AG-EF) — catches a state you can enter and never leave, which plain reachability misses. |
| `validate_spec` | Schema check without running it; the error names the offending key. |
| `spec_help` | The format, with a worked example **and its actual verdict**. |

## The spec format

```json
{
  "name": "mutex",
  "fields": ["a", "b", "lock"],
  "initial": {"a": 0, "b": 0, "lock": 0},
  "transitions": [
    {"label": "a_enter", "when": {"a": 0, "lock": 0}, "set": {"a": 1, "lock": 1}},
    {"label": "a_exit",  "when": {"a": 1},            "set": {"a": 0, "lock": 0}}
  ],
  "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}},
  "goal": {"require": {"a": 1}}
}
```

`when` is a conjunction of `field == value` tests (omit it for always-enabled). `set` assigns a
literal, or `{"incr": n}` / `{"decr": n}` for integers. An invariant is `{"forbid": {...}}` (fails
when every listed field matches) or `{"require": {...}}` (fails unless they do).

Integers are **bounded, and the bound is checked** — `int_bound` (default 64) is the largest magnitude
a field may hold. A run that would carry a field past it stops and reports `exhaustive: false` rather
than saturating the value, because a silently truncated search reports "holds" for states it never
visited. See [Honest scope](#honest-scope) for how to read the resulting verdict.

## Why declarative

An MCP server that `exec`'d agent-supplied Python would be a remote code execution hole with extra
steps. Specs here are data: a field value that looks like `__import__('os').system(...)` stays a
string and is compared as one. There is a test that asserts exactly that.

## No SDK? Still usable.

The tools are plain functions. `dispatch` is the same entry point the transport uses, so you can
call it from a script or a test without an agent in the loop:

```python
from minicheck_mcp import dispatch
dispatch("check_invariant", {"spec": my_spec})
```

Without `mcp` installed, `minicheck-mcp` prints a JSON error explaining how to install it and exits
non-zero, rather than traceback-ing.

## Honest scope

**Read the verdict as three-valued.** This is the part that matters most for an agent, because an
agent reads a field and acts on it rather than bringing judgement to a paragraph.

| `all_hold` | `verdict` | meaning |
|---|---|---|
| `true` | `PROVED` | every reachable state was enumerated; nothing violated the invariant |
| `false` | `REFUTED` | a counterexample is attached and it replays against your spec |
| `null` | `UNDETERMINED` | the search did not finish. **Not a pass.** |
| `null` | `ERROR` | with `ok: false` — no verdict was produced at all |

Every response carries `all_hold` and `holds` explicitly, including errors. An earlier version
omitted them on failure, so `result.get("all_hold")` returned `None` for a crash and for a genuine
undetermined result alike — and both are falsy, exactly like a refutation.

When `exhaustive` is `false`, the response also carries `incomplete_reason` and `advice` naming what
to change. A `warnings` array appears when an invariant is trivially satisfied — it genuinely holds,
but verifies nothing.

**What it proves.** That a finite declarative state machine does or does not satisfy an invariant
over every interleaving, within the declared bounds.

**What it does not prove.**

- Nothing about your implementation — only about the spec you sent. A spec abstracts.
- Nothing outside `int_bound` (default 64) or the 200,000-state cap. Exceeding either yields
  `UNDETERMINED`, never a silent pass.
- Nothing about liveness beyond AG-EF, and nothing in LTL.

**Nothing in a spec is ever executed.** A spec is data: field names, literals, and comparisons. There
is no `eval`, no `exec`, and no code path that turns a string in a spec into a callable. That is why
the declarative loader exists rather than accepting Python.

## What is not here

This is the engine and a safe way to call it. The maintained hazard-property corpora, the
composition analysis that finds hazards which exist only when two components are combined, and the
evidence trail that makes a verdict auditable afterwards are the commercial offering. This server is
MIT and stays that way.

## Tests

```
pip install -e ".[test]" && pytest
```

83 tests, every tool through the real `dispatch` path, including malformed input, unknown tools, and
the no-code-execution guarantee.

## The portfolio

Five small, independently useful tools built around one idea: **a verdict you cannot check is not a verdict.**

| | |
|---|---|
| [`minicheck`](https://github.com/nickharris808/minicheck) | An explicit-state model checker in ~1308 lines. Shortest counterexamples, no required dependencies. |
| [`protocol-bench`](https://github.com/nickharris808/protocol-bench) | 15 published IEEE 802.11 / 3GPP procedures with ground truth. A claimed detection must **replay**. |
| [`minicheck-mcp`](https://github.com/nickharris808/minicheck-mcp) ← *you are here* | The checker as an **MCP server** — let an agent verify a state machine instead of guessing. |
| [`polyfrac`](https://github.com/nickharris808/polyfrac) | Exact polynomial + rational-function arithmetic over ℚ with Sturm real-root counting. Zero deps. |
| [`failclosed`](https://github.com/nickharris808/failclosed) | Default-deny ASGI middleware: a gated endpoint succeeds only on an affirmative verdict. |
| [`protocol-bench-action`](https://github.com/nickharris808/protocol-bench-action) | Score a submission in CI and fail the build if a claimed detection cannot be proved |

Try it in your browser: **[live demo](https://huggingface.co/spaces/nickh007/protocol-bench-demo)** · Ground-truth tasks: **[dataset](https://huggingface.co/datasets/nickh007/protocol-bench)**

### The commercial offering

These are the engine. What is **not** open source is what makes it useful at scale: the maintained
hazard-property corpora, composition analysis that finds hazards existing only when two components
are combined, the trust-model sensitivity sweep, and the evidence trail that makes a verdict auditable
after the fact. The tools above are MIT and stay that way.

## Licence

MIT. See `LICENSE`.
