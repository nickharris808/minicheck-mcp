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

Integers are clamped to keep the state space finite.
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


def _err(e: Exception) -> dict:
    return {"ok": False, "error": type(e).__name__, "message": str(e)}


def check_invariant(spec: dict, invariant: str | None = None) -> dict:
    """Check safety invariants over every reachable state.

    Returns a verdict per invariant, with a SHORTEST counterexample trace where one fails.
    """
    try:
        model = protocol_from_spec(spec)
    except SpecError as e:
        return _err(e)
    if not model.invariants:
        return {"ok": False, "error": "SpecError", "message": "spec declares no invariants"}

    res = _check_safety(model)
    props = res["properties"]
    if invariant is not None:
        if invariant not in props:
            return {
                "ok": False,
                "error": "SpecError",
                "message": f"no invariant named {invariant!r}; have {sorted(props)}",
            }
        props = {invariant: props[invariant]}

    out = {"ok": True, "reachable_states": res["reachable_states"], "invariants": {}}
    for name, r in props.items():
        entry: dict[str, Any] = {"holds": r["holds"]}
        if r["counterexample"]:
            entry["counterexample"] = [{"label": s["label"], "state": s["state"]} for s in r["counterexample"]]
            entry["steps"] = len(r["counterexample"]) - 1
        out["invariants"][name] = entry
    out["all_hold"] = all(v["holds"] for v in out["invariants"].values())
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
        return {"ok": False, "error": "SpecError", "message": "spec declares no 'goal'"}
    r = _check_liveness(model)
    out = {"ok": True, "holds": r["holds"], "note": r.get("note")}
    if not r["holds"] and r.get("counterexample"):
        out["trap_trace"] = [{"label": s["label"], "state": s["state"]} for s in r["counterexample"]]
    for k in ("reachable_states", "goal_states"):
        if k in r:
            out[k] = r[k]
    return out


def validate_spec(spec: dict) -> dict:
    """Schema-check a spec without running it."""
    try:
        _validate_spec(spec)
    except SpecError as e:
        return {"ok": False, "valid": False, "error": type(e).__name__, "message": str(e)}
    return {"ok": True, "valid": True}


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
            "spec_help first if unsure of the format."
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
            "Catches states you can enter and never leave."
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
        return {"ok": False, "error": "UnknownTool", "message": f"no tool named {name!r}; have {sorted(TOOLS)}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"ok": False, "error": "BadArguments", "message": str(e)}
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
