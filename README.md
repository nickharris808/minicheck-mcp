# minicheck-mcp

[![PyPI](https://img.shields.io/badge/pypi-minicheck--mcp-blue)](https://pypi.org/project/minicheck-mcp/)
[![CI](https://img.shields.io/badge/ci-passing-brightgreen)](../.github/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-19%20passing-brightgreen)](tests/)
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
pip install "minicheck-mcp[mcp]"
```

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

Integers are clamped so a runaway counter cannot produce an unbounded search.

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

## What is not here

This is the engine and a safe way to call it. The maintained hazard-property corpora, the
composition analysis that finds hazards which exist only when two components are combined, and the
evidence trail that makes a verdict auditable afterwards are the commercial offering. This server is
MIT and stays that way.

## Related

- [`minicheck`](../minicheck) — the checker itself, importable directly.
- [`protocol-bench`](../protocol-bench) — 15 published IEEE/3GPP procedures with ground truth.

## Tests

```
pip install -e ".[test]" && pytest
```

19 tests, every tool through the real `dispatch` path, including malformed input, unknown tools, and
the no-code-execution guarantee.

## Licence

MIT. See `LICENSE`.
