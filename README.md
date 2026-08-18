# minicheck-mcp

[![install](https://img.shields.io/badge/install-git%2Bhttps-blue)](https://github.com/nickharris808/minicheck-mcp#install)
[![CI](https://github.com/nickharris808/minicheck-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/nickharris808/minicheck-mcp/actions/workflows/ci.yml)
[![tests](https://img.shields.io/badge/tests-102%20passing-brightgreen)](tests/)
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

The spec it sends is **data, never code, so nothing the agent submits is executed** — and what comes
back is a verdict with a shortest counterexample trace.

## Install

```
# from GitHub (PyPI release pending)
pip install "minicheck-mcp @ git+https://github.com/nickharris808/minicheck-mcp.git"
pip install "minicheck-mcp[mcp] @ git+https://github.com/nickharris808/minicheck-mcp.git"  # + the MCP SDK
```

> `pip install minicheck-mcp` does not work yet — the package is not on PyPI. Install from GitHub
> as shown above; that pulls in `minicheck` automatically. `python build_pypi.py` produces a
> PyPI-uploadable artifact for when both packages are published (PyPI rejects the direct dependency
> reference this package uses to stay installable without an index).

Then register it (`claude_desktop_config.json`, or any MCP client):

```json
{ "mcpServers": { "minicheck": { "command": "minicheck-mcp" } } }
```

The repo ships this as `mcp.json`.

## 30-second quickstart

Ask the agent: *"I have a retry loop that increments a counter until it succeeds. Check that it can't
retry more than 3 times."* It sends this spec to `check_invariant`:

```json
{
  "name": "retry",
  "fields": ["tries", "done"],
  "initial": {"tries": 0, "done": 0},
  "transitions": [
    {"label": "attempt", "when": {"done": 0}, "set": {"tries": {"incr": 1}}},
    {"label": "succeed", "when": {"done": 0}, "set": {"done": 1}}
  ],
  "invariants": {"bounded_retries": {"forbid": {"tries": 4}}}
}
```

and gets back — reproduce it with
`python -c "from minicheck_mcp import dispatch; import json; print(json.dumps(dispatch('check_invariant', {'spec': SPEC}), indent=2))"`:

```json
{
  "ok": true,
  "reachable_states": 129,
  "exhaustive": false,
  "invariants": {
    "bounded_retries": {
      "holds": false,
      "counterexample": [
        {"label": null,      "state": {"tries": 0, "done": 0}},
        {"label": "attempt", "state": {"tries": 1, "done": 0}},
        {"label": "attempt", "state": {"tries": 2, "done": 0}},
        {"label": "attempt", "state": {"tries": 3, "done": 0}},
        {"label": "attempt", "state": {"tries": 4, "done": 0}}
      ],
      "steps": 4
    }
  },
  "incomplete_reason": "IntBoundExceeded: transition 'attempt' drives field 'tries' to 65, outside int_bound 64. The state space is not finite under this bound, so no exhaustive verdict is available. Re-run with int_bound >= 65.",
  "advice": "the state space was not fully explored, so any invariant not refuted below is UNDETERMINED (null), not proved. Raise int_bound or add a 'when' guard that bounds the growing field, then check again.",
  "all_hold": false,
  "verdict": "REFUTED",
  "verdict_means": "a counterexample was found; it starts at the initial state and replays"
}
```

Not "this might loop forever" — the exact four steps that break it.

Read the whole reply, though, and this quickstart is the reason why: `exhaustive` is **false**. The
refutation stands regardless — a counterexample carries its own witness and that trace replays — but
nothing else in this spec was established, because `attempt` has no guard and drives `tries` past
`int_bound`. Refuting takes one witness; proving takes the whole space.

## Tutorial — what a session actually looks like

The agent has written a session lifecycle and wants to know whether a session can be used after it
has been closed. Here is the whole exchange.

**1. The agent asks for the format** (`spec_help`), then sends `check_invariant`:

```json
{
  "name": "session",
  "fields": ["state", "used"],
  "initial": {"state": 0, "used": 0},
  "transitions": [
    {"label": "open",  "when": {"state": 0}, "set": {"state": 1}},
    {"label": "use",   "when": {"state": 1}, "set": {"used": 1}},
    {"label": "close", "when": {"state": 1}, "set": {"state": 2}},
    {"label": "reopen","when": {"state": 2}, "set": {"state": 1}}
  ],
  "invariants": {"no_use_after_close": {"forbid": {"state": 2, "used": 1}}}
}
```

**2. It gets a refutation with the exact path:**

```json
{
  "ok": true,
  "verdict": "REFUTED",
  "exhaustive": true,
  "reachable_states": 5,
  "all_hold": false,
  "invariants": {
    "no_use_after_close": {
      "holds": false,
      "steps": 3,
      "counterexample": [
        {"label": null,    "state": {"state": 0, "used": 0}},
        {"label": "open",  "state": {"state": 1, "used": 0}},
        {"label": "use",   "state": {"state": 1, "used": 1}},
        {"label": "close", "state": {"state": 2, "used": 1}}
      ]
    }
  }
}
```

The invariant as written forbids *ever having used* a closed session, which is not what the agent
meant — it meant "no `use` transition while closed". The counterexample makes the difference
concrete rather than leaving it to a plausible-sounding paragraph.

**3. The agent fixes the model and re-runs.** `used` should mean "used since this session opened",
so `close` clears it:

```json
{"label": "close", "when": {"state": 1}, "set": {"state": 2, "used": 0}}
```

```json
{"ok": true, "verdict": "PROVED", "exhaustive": true, "reachable_states": 4, "all_hold": true}
```

`PROVED` **and** `exhaustive: true` is the pair to read. The first cannot be issued without the
second, but checking both makes the habit explicit — and the habit is what protects you on the day
a spec grows past the bound.

**4. What the agent must not do.** If the reply is `"verdict": "UNDETERMINED"`, that is not a pass.
It means the search stopped early — read `incomplete_reason` and `advice`, bound the growing field,
and ask again. If `ok` is `false`, no verdict exists at all and `all_hold` is `null`.

## Tools

| Tool | What it does |
|---|---|
| `check_invariant` | Exhaustive reachability. Shortest counterexample when a property fails. |
| `check_liveness` | Every reachable state can **still** reach the goal (AG-EF) — catches a state you can enter and never leave, which plain reachability misses. |
| `validate_spec` | Schema check without running it; the error names the offending key. |
| `visualise` | A **Mermaid state diagram** with the counterexample highlighted and its steps numbered — renders directly in GitHub Markdown, so an agent can show a user *why* rather than describe it. |
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

Every response also carries `verdict_means`, a one-line explanation an agent can quote to a user
verbatim rather than paraphrasing (and possibly softening) it.

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

## Troubleshooting

**`ok: false, error: "SpecError"`.** The spec is malformed and the message names the key. Call
`validate_spec` first, or `spec_help` for the format with a worked example.

**`verdict: "UNDETERMINED"` on a spec I expected to pass.** The search did not cover the whole state
space — usually a field that grows without bound. Read `incomplete_reason` and `advice`. Add a
`when` guard that stops the growth. **Do not treat this as a pass.**

**`ok: false, error: "BadArguments"`.** The tool was called with an argument it does not take. Every
tool takes `spec`; `check_invariant` also takes an optional `invariant` name.

**`ok: false` on `check_liveness` with `"spec declares no 'goal'"`.** Liveness needs something to
reach. Add a `goal` block in the same shape as an invariant.

**A `warnings` array appeared and the invariant still says `holds: true`.** The invariant names a
value the bounded space cannot represent, so it is satisfied for a reason unrelated to your
protocol — usually a typo in the literal, or an `int_bound` below the value you meant to forbid.

**The server exits immediately with a JSON error.** The MCP SDK is not installed:
`pip install "minicheck-mcp[mcp] @ git+https://github.com/nickharris808/minicheck-mcp.git"`. The
tools remain importable and testable without it via `from minicheck_mcp import dispatch`.

**My agent treats an error as "the property is fine".** It should not be able to: every response
carries `all_hold` and `holds` explicitly, and both are `null` on any error, alongside
`verdict: "ERROR"`. Branch on `result["ok"]` first.

## Performance

Bounded by the underlying checker. Specs arrive here declaratively, which is the checker's compiled
path — roughly 2.5×10⁵–7.5×10⁵ states/second in CPython 3.11 on an M-series laptop, reproducible by
running `python bench.py` in the [`minicheck`](https://github.com/nickharris808/minicheck)
repository. A spec that fits in a few tens of thousands of states answers in well under a second.
There is no measured bottleneck in the server layer itself — it is a thin dispatch.

## FAQ

**"Doesn't running a spec from a language model let it execute code?"**
No, and this is why the declarative format exists. A spec is data: field names, literals, and equality
comparisons. There is no `eval`, no `exec`, and no code path that turns a string in a spec into a
callable. A field value that looks like `__import__('os').system(...)` stays a string and is compared
as one. There is a test that asserts exactly that, and the adversarial suite fires code-shaped
payloads at every tool. (`minicheck`'s Python `Model` API is different — that *is* code, and untrusted
models from it deserve the caution any untrusted Python does. This server does not expose it.)

**"Why not just let the agent write Python and run it?"**
An MCP server that `exec`'d agent-supplied Python would be a remote code execution hole with extra
steps. The declarative format costs expressiveness and buys a property you can state in one sentence
and test.

**"My agent read `all_hold` and concluded the property was fine, but there was an error."**
It should not be able to: every response carries `all_hold` and `holds` explicitly, and both are
`null` on any error, alongside `verdict: "ERROR"` and `ok: false`. An earlier version *omitted* them
on failure, so `result.get("all_hold")` returned `None` for a crash and for a genuine undetermined
result alike — and both are falsy, exactly like a refutation. Branch on `result["ok"]` first, then on
`verdict`, never on the truthiness of `all_hold`.

**"Why is there a `verdict_means` string in every reply?"**
Because an agent paraphrasing a verdict tends to soften it, and "the check was inconclusive" becomes
"it looks fine" in two more hops. `verdict_means` is a one-line explanation the agent can quote to a
user verbatim.

**"`UNDETERMINED` — should the agent retry, or report success?"**
Neither by default. It means the search stopped early, so nothing was established. Read
`incomplete_reason` and `advice`, which name what to change — usually a field growing without bound.
Bound it and ask again. Reporting it as a pass is the failure mode this whole package is shaped
against.

**"Do I need the MCP SDK?"**
Only to serve it over the transport. The tools are plain functions: `from minicheck_mcp import
dispatch` is the same entry point the transport uses, so you can call it from a script or a test with
no agent in the loop. Without `mcp` installed the `minicheck-mcp` command prints a JSON error saying
how to install it and exits non-zero, rather than traceback-ing.

**"Is it production-ready?"**
Yes, and fully tested — but the surrounding agent ecosystem moves quickly, so the MCP surface is the
part most likely to need a version bump. The checker underneath is
[`minicheck`](https://github.com/nickharris808/minicheck) and is stable.

**"Something here gave me a confident answer that was wrong."**
Worth an issue rather than a workaround; please include the spec. A false `holds: true` reachable
from an agent-facing server is the most serious bug this package can have, and one of exactly that
kind was found, fixed and disclosed in `minicheck` 0.1.0.

## Tests

```
pip install -e ".[test]" && pytest
```

```console
$ pytest -q
........................................................................ [ 74%]
.........................                                                [100%]
100 passed in 2.31s
```

102 tests, every tool through the real `dispatch` path, including malformed input, unknown tools, and
the no-code-execution guarantee. One asserts this README's own test count against
`pytest --collect-only`, so the badge cannot drift.

## The portfolio

| | |
|---|---|
| [`minicheck`](https://github.com/nickharris808/minicheck) | The engine: an explicit-state model checker with a CLI. Shortest counterexamples, no required dependencies. |
| [`protocol-bench`](https://github.com/nickharris808/protocol-bench) | Published IEEE 802.11 / 3GPP procedures with ground-truth verdicts. A claimed detection must **replay**. |
| [`specforge`](https://github.com/nickharris808/specforge) | A benchmark that cannot be memorised — ground truth is *computed* by the checker, not written down. |
| [`minicheck-mcp`](https://github.com/nickharris808/minicheck-mcp) ← *you are here* | The checker as an **MCP server**, so an agent can verify a state machine instead of guessing. |
| [`minicheck-action`](https://github.com/nickharris808/minicheck-action) | Model-check every spec in a repo, in CI. Diagrams in the PR, SARIF in the Security tab. |
| [`protocol-bench-action`](https://github.com/nickharris808/protocol-bench-action) | Score a submission in CI and fail the build if a claimed detection cannot be proved by replay. |
| [`failclosed`](https://github.com/nickharris808/failclosed) | Default-deny ASGI middleware: a gated endpoint succeeds only on an affirmative verdict. |
| [`polyfrac`](https://github.com/nickharris808/polyfrac) | Exact polynomial and rational-function arithmetic over ℚ with Sturm real-root counting. Zero deps. |
| [**the docs site**](https://nickharris808.github.io/verification-docs/) | The front door: why a verdict you cannot check is not a verdict, and how these compose. |

One idea runs through all of them: **a verdict you cannot check is not a verdict** — and its
corollary, which governs every surface here: *undetermined is not a pass.*

**Try it in the browser** · [model-check a state machine](https://huggingface.co/spaces/nickh007/protocol-bench-demo) · [the specforge leaderboard](https://huggingface.co/spaces/nickh007/specforge-leaderboard)

**Ground-truth data** · [protocol-bench](https://huggingface.co/datasets/nickh007/protocol-bench) · [specforge](https://huggingface.co/datasets/nickh007/specforge)

### The commercial offering

These are the engine. What is **not** open source is what makes it useful at scale: the maintained
hazard-property corpora, composition analysis that finds hazards existing only when two components
are combined, the trust-model sensitivity sweep, and the evidence trail that makes a verdict auditable
after the fact. The tools above are MIT and stay that way.

## Documentation

Full documentation, including the concepts guide and an honest comparison against TLA+, SPIN, Alloy
and CBMC, is at **[https://nickharris808.github.io/verification-docs/](https://nickharris808.github.io/verification-docs/)**.

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). A counterexample
that this tool gets wrong is the single most useful thing you can send.

## Citing

Citation metadata is in [CITATION.cff](CITATION.cff); GitHub renders a *Cite this repository* button
from it.

## Licence

MIT. See [LICENSE](LICENSE).
