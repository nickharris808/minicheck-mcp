"""An MCP server exposing a model checker to AI agents.

Agents write state machines constantly — retry logic, lock protocols, session lifecycles, agent
hand-off graphs — and they have no way to check one. They reason about it in prose and get it wrong
in exactly the way humans do: they miss an interleaving.

This server gives an agent a real decision procedure. It takes a **declarative** spec (data, never
code, so nothing here executes what the agent sends) and returns a verdict with a shortest
counterexample trace when the property fails.

Tools
-----
``check_invariant``  exhaustive reachability; returns a shortest counterexample when it fails
``check_liveness``   every reachable state can still reach the goal (AG-EF, not mere reachability)
``validate_spec``    schema check with a message naming the offending key
``spec_help``        the spec format, with a worked example

Run it::

    minicheck-mcp                      # stdio transport
"""

from __future__ import annotations

import json
from typing import Any

from minicheck import (
    SpecError,
    protocol_from_spec,
)
from minicheck import (
    check_liveness as _check_liveness,
)
from minicheck import (
    check_safety as _check_safety,
)
from minicheck import (
    spec_warnings as _spec_warnings,
)
from minicheck import (
    validate_spec as _validate_spec,
)

SPEC_HELP = """\
A spec is JSON. No code is executed.

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

  fields       state variable names
  initial      the starting value of every field
  transitions  "when" is a conjunction of field == value tests (omit = always enabled);
               "set" assigns a literal, or {"incr": n} / {"decr": n} for integers
  invariants   {"forbid": {...}} fails when every listed field matches;
               {"require": {...}} fails unless every listed field matches
  goal         optional, same shape, used by check_liveness

Integers are BOUNDED, and the bound is checked rather than silently applied. `int_bound` (default
64) is the largest magnitude a field may take. If a run would carry a field past it, the check stops
and reports `exhaustive: false` instead of saturating the value — because a search that was quietly
truncated would report "holds" for states it never visited.

So read the verdicts this way:

  holds: true    proved — every reachable state was enumerated and none violated the invariant
  holds: false   refuted — a counterexample trace is attached and it replays against your spec
  holds: null    UNDETERMINED — the search did not finish. NOT a pass. Raise int_bound, or add a
                 guard ("when") so the field stops growing, then ask again.

`all_hold` follows the same three values. Never treat null as true.
"""

_EXAMPLE = {
    "name": "mutex",
    "fields": ["a", "b", "lock"],
    "initial": {"a": 0, "b": 0, "lock": 0},
    "transitions": [
        {"label": "a_enter", "when": {"a": 0}, "set": {"a": 1, "lock": 1}},
        {"label": "b_enter", "when": {"b": 0}, "set": {"b": 1, "lock": 1}},
    ],
    "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}},
}


def _err(e: Exception, message: str | None = None, error: str | None = None) -> dict:
    """An error response that cannot be mistaken for a verdict.

    Every failure carries ``all_hold: None`` and ``holds: None`` explicitly. An agent that writes
    ``if result.get("all_hold"):`` gets a falsy value either way, but one that writes
    ``if result["all_hold"] is False:`` — checking for a genuine refutation — no longer sees a
    crashed call as "the property is fine". Previously an error returned neither key at all, so an
    exception and a clean pass were indistinguishable to anything reading the verdict fields.
    """
    return {
        "ok": False,
        "error": error or type(e).__name__,
        "message": message or str(e),
        "all_hold": None,
        "holds": None,
        "verdict": "ERROR",
        "advice": "this call did not produce a verdict; nothing about the spec's safety was established",
    }


def check_invariant(spec: dict, invariant: str | None = None) -> dict:
    """Check safety invariants over every reachable state.

    Returns a verdict per invariant, with a SHORTEST counterexample trace where one fails.
    """
    try:
        model = protocol_from_spec(spec)
    except SpecError as e:
        return _err(e)
    if not model.invariants:
        return _err(
            ValueError("no invariants"),
            "spec declares no invariants; there is nothing to check",
            error="SpecError",
        )

    try:
        res = _check_safety(model)
    except Exception as e:
        return _err(e)
    props = res["properties"]
    if invariant is not None:
        if invariant not in props:
            return _err(
                KeyError(invariant),
                f"no invariant named {invariant!r}; have {sorted(props)}",
                error="SpecError",
            )
        props = {invariant: props[invariant]}

    out: dict[str, Any] = {
        "ok": True,
        "reachable_states": res["reachable_states"],
        # LOUD precondition: whether the sweep actually covered the whole space. A verdict of
        # `holds: true` is only meaningful when this is true, so it is reported next to it.
        "exhaustive": res["exhaustive"],
        "invariants": {},
    }
    if not res["exhaustive"]:
        out["incomplete_reason"] = res.get("incomplete_reason", "the search did not finish")
        out["advice"] = (
            "the state space was not fully explored, so any invariant not refuted below is "
            "UNDETERMINED (null), not proved. Raise int_bound or add a 'when' guard that bounds the "
            "growing field, then check again."
        )
    # An invariant that cannot be violated by construction is reported as trivial. It genuinely
    # holds, but saying only "holds: true" would let a reader think the protocol was verified
    # against something meaningful.
    warnings = _spec_warnings(spec)
    if warnings:
        out["warnings"] = warnings
    for name, r in props.items():
        entry: dict[str, Any] = {"holds": r["holds"]}
        if r.get("reason"):
            entry["reason"] = r["reason"]
        if r["counterexample"]:
            entry["counterexample"] = [{"label": s["label"], "state": s["state"]} for s in r["counterexample"]]
            entry["steps"] = len(r["counterexample"]) - 1
        out["invariants"][name] = entry

    # Three-valued, and it must not collapse. `False` beats `None` beats `True`: a refutation is a
    # definite answer, an undetermined search is not a pass, and only an all-proved set is `True`.
    verdicts = [v["holds"] for v in out["invariants"].values()]
    if any(v is False for v in verdicts):
        out["all_hold"] = False
    elif any(v is None for v in verdicts):
        out["all_hold"] = None
    else:
        out["all_hold"] = True
    out["verdict"] = {True: "PROVED", False: "REFUTED", None: "UNDETERMINED"}[out["all_hold"]]
    return out


def check_liveness(spec: dict) -> dict:
    """Check that EVERY reachable state can still reach the goal (AG-EF).

    Stronger than "the goal is reachable": it catches a state you can enter and never leave.
    """
    try:
        model = protocol_from_spec(spec)
    except SpecError as e:
        return _err(e)
    if model.goal is None:
        return _err(
            ValueError("no goal"),
            "spec declares no 'goal', so there is no liveness question to answer; add a "
            "'goal' block naming the state that must remain reachable",
            error="SpecError",
        )
    try:
        r = _check_liveness(model)
    except Exception as e:
        return _err(e)
    out: dict[str, Any] = {
        "ok": True,
        "holds": r["holds"],
        "verdict": {True: "PROVED", False: "REFUTED", None: "UNDETERMINED"}[r["holds"]],
        "note": r.get("note"),
    }
    if r["holds"] is False and r.get("counterexample"):
        out["trap_trace"] = [{"label": s["label"], "state": s["state"]} for s in r["counterexample"]]
    for k in ("reachable_states", "goal_states"):
        if k in r:
            out[k] = r[k]
    return out


def validate_spec(spec: dict, int_bound: int | None = None) -> dict:
    """Schema-check a spec without running it.

    Checks the same `int_bound` the checker would use, so a spec that validates here will not be
    rejected for a bound reason later.
    """
    try:
        _validate_spec(spec) if int_bound is None else _validate_spec(spec, int_bound=int_bound)
    except SpecError as e:
        return {
            "ok": False,
            "valid": False,
            "error": type(e).__name__,
            "message": str(e),
            "all_hold": None,
            "holds": None,
            "verdict": "ERROR",
        }
    out = {"ok": True, "valid": True}
    warnings = _spec_warnings(spec) if int_bound is None else _spec_warnings(spec, int_bound)
    if warnings:
        out["warnings"] = warnings
    return out


def spec_help() -> dict:
    """The spec format, with a worked example and its verdict."""
    return {"ok": True, "format": SPEC_HELP, "example": _EXAMPLE, "example_result": check_invariant(_EXAMPLE)}


TOOLS = {
    "check_invariant": check_invariant,
    "check_liveness": check_liveness,
    "validate_spec": validate_spec,
    "spec_help": spec_help,
}

TOOL_SCHEMAS = [
    {
        "name": "check_invariant",
        "description": (
            "Exhaustively check safety invariants of a declarative state-machine spec. "
            "Returns a shortest counterexample trace when an invariant fails. Call "
            "spec_help first if unsure of the format. "
            "VERDICTS ARE THREE-VALUED: `all_hold` is true (proved over the whole reachable "
            "space), false (refuted, with a replayable counterexample), or null (UNDETERMINED — "
            "the search did not finish). Null is NOT a pass; check `exhaustive` and follow "
            "`advice` to make the space finite, then ask again. `ok: false` means no verdict "
            "was produced at all."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "spec": {"type": "object", "description": "The declarative state-machine spec."},
                "invariant": {"type": "string", "description": "Optional: check only this named invariant."},
            },
            "required": ["spec"],
        },
    },
    {
        "name": "check_liveness",
        "description": (
            "Check that every reachable state can still reach the spec's goal (AG-EF). "
            "Catches states you can enter and never leave. `holds` is three-valued: true, "
            "false (with a trap trace), or null when the question could not be settled. "
            "Requires a 'goal' in the spec; without one it returns an error, not a pass."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"spec": {"type": "object"}},
            "required": ["spec"],
        },
    },
    {
        "name": "validate_spec",
        "description": "Schema-check a spec without running it. Returns the offending key on failure.",
        "inputSchema": {
            "type": "object",
            "properties": {"spec": {"type": "object"}},
            "required": ["spec"],
        },
    },
    {
        "name": "spec_help",
        "description": "The spec format, with a worked example and its verdict.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def dispatch(name: str, arguments: dict | None = None) -> dict:
    """Route a tool call. Used by the MCP transport and directly by the tests."""
    args = arguments or {}
    fn = TOOLS.get(name)
    if fn is None:
        return _err(KeyError(name), f"no tool named {name!r}; have {sorted(TOOLS)}", error="UnknownTool")
    if not isinstance(args, dict):
        return _err(
            TypeError("arguments"),
            f"arguments must be an object, got {type(args).__name__}",
            error="BadArguments",
        )
    try:
        return fn(**args)
    except TypeError as e:
        return _err(e, f"bad arguments for {name!r}: {e}", error="BadArguments")
    except Exception as e:  # never crash the transport
        return _err(e)


def main() -> int:
    """Serve over stdio using the MCP SDK, if it is installed."""
    try:
        import mcp.server.stdio  # noqa: F401
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        from mcp.types import TextContent, Tool
    except ImportError:
        print(
            json.dumps(
                {
                    "error": "the MCP SDK is not installed",
                    "fix": "pip install 'minicheck-mcp[mcp]'",
                    "note": "the tools are importable and testable without it: "
                    "from minicheck_mcp.server import dispatch",
                },
                indent=2,
            )
        )
        return 1

    import asyncio

    server = Server("minicheck")

    @server.list_tools()
    async def _list() -> list:
        return [Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"]) for t in TOOL_SCHEMAS]

    @server.call_tool()
    async def _call(name: str, arguments: dict) -> list:
        return [TextContent(type="text", text=json.dumps(dispatch(name, arguments), indent=2, default=str))]

    async def _run():
        async with mcp.server.stdio.stdio_server() as (r, w):
            await server.run(
                r,
                w,
                InitializationOptions(
                    server_name="minicheck",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(notification_options=None, experimental_capabilities={}),
                ),
            )

    asyncio.run(_run())
    return 0
