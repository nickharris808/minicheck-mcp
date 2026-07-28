"""Tests for the MCP server.

Every tool is exercised through `dispatch`, which is the same entry point the MCP transport uses, so
these tests cover the real call path without needing the SDK or a running agent.
"""

import pytest
from minicheck_mcp import TOOL_SCHEMAS, TOOLS, dispatch

BROKEN = {
    "name": "mutex",
    "fields": ["a", "b"],
    "initial": {"a": 0, "b": 0},
    "transitions": [
        {"label": "a_enter", "when": {"a": 0}, "set": {"a": 1}},
        {"label": "b_enter", "when": {"b": 0}, "set": {"b": 1}},
    ],
    "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}},
}
FIXED = {
    **BROKEN,
    "fields": ["a", "b", "lock"],
    "initial": {"a": 0, "b": 0, "lock": 0},
    "transitions": [
        {"label": "a_enter", "when": {"a": 0, "lock": 0}, "set": {"a": 1, "lock": 1}},
        {"label": "b_enter", "when": {"b": 0, "lock": 0}, "set": {"b": 1, "lock": 1}},
    ],
}


# --------------------------------------------------------------------------- check_invariant
def test_a_broken_spec_returns_a_shortest_counterexample():
    r = dispatch("check_invariant", {"spec": BROKEN})
    assert r["ok"] is True and r["all_hold"] is False
    inv = r["invariants"]["not_both"]
    assert inv["holds"] is False
    assert [s["label"] for s in inv["counterexample"][1:]] == ["a_enter", "b_enter"]
    assert inv["steps"] == 2


def test_a_fixed_spec_holds():
    r = dispatch("check_invariant", {"spec": FIXED})
    assert r["ok"] is True and r["all_hold"] is True
    assert "counterexample" not in r["invariants"]["not_both"]


def test_a_single_invariant_can_be_selected():
    spec = {**BROKEN, "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}, "trivial": {"forbid": {"a": 99}}}}
    r = dispatch("check_invariant", {"spec": spec, "invariant": "trivial"})
    assert set(r["invariants"]) == {"trivial"}
    assert r["invariants"]["trivial"]["holds"] is True


def test_selecting_an_unknown_invariant_is_a_clean_error():
    r = dispatch("check_invariant", {"spec": BROKEN, "invariant": "nope"})
    assert r["ok"] is False and "no invariant named" in r["message"]


def test_a_spec_with_no_invariants_is_a_clean_error():
    r = dispatch("check_invariant", {"spec": {**BROKEN, "invariants": {}}})
    assert r["ok"] is False and "no invariants" in r["message"]


# --------------------------------------------------------------------------- check_liveness
def test_liveness_reports_a_trap():
    spec = {
        "fields": ["n"],
        "initial": {"n": 0},
        "transitions": [
            {"label": "goal", "when": {"n": 0}, "set": {"n": 1}},
            {"label": "dead", "when": {"n": 0}, "set": {"n": 2}},
        ],
        "invariants": {"t": {"forbid": {"n": 99}}},
        "goal": {"require": {"n": 1}},
    }
    r = dispatch("check_liveness", {"spec": spec})
    assert r["ok"] is True and r["holds"] is False
    assert r["trap_trace"][-1]["state"]["n"] == 2


def test_liveness_holds_when_the_goal_is_always_still_reachable():
    spec = {
        "fields": ["n"],
        "initial": {"n": 0},
        "transitions": [{"label": "go", "when": {"n": 0}, "set": {"n": 1}}],
        "invariants": {"t": {"forbid": {"n": 99}}},
        "goal": {"require": {"n": 1}},
    }
    assert dispatch("check_liveness", {"spec": spec})["holds"] is True


def test_liveness_without_a_goal_is_a_clean_error():
    r = dispatch("check_liveness", {"spec": BROKEN})
    assert r["ok"] is False and "no 'goal'" in r["message"]


# --------------------------------------------------------------------------- validate / help
def test_validate_accepts_a_good_spec_and_rejects_a_bad_one():
    assert dispatch("validate_spec", {"spec": BROKEN})["valid"] is True
    bad = dispatch("validate_spec", {"spec": {"fields": ["a"]}})
    assert bad["valid"] is False and bad["message"]


def test_spec_help_ships_a_worked_example_that_actually_runs():
    r = dispatch("spec_help")
    assert r["ok"] is True and "transitions" in r["format"]
    assert r["example_result"]["ok"] is True
    assert r["example_result"]["all_hold"] is False  # the example is the broken mutex


# --------------------------------------------------------------------------- robustness
def test_a_malformed_spec_returns_an_error_and_never_raises():
    r = dispatch("check_invariant", {"spec": {"fields": "not a list"}})
    assert r["ok"] is False and r["error"] == "SpecError"


def test_an_unknown_tool_is_reported_not_raised():
    r = dispatch("no_such_tool", {})
    assert r["ok"] is False and r["error"] == "UnknownTool"


def test_bad_arguments_are_reported_not_raised():
    r = dispatch("check_invariant", {"wrong_kwarg": 1})
    assert r["ok"] is False and r["error"] == "BadArguments"


def test_no_code_is_executed_from_a_spec():
    spec = {
        "fields": ["a"],
        "initial": {"a": "__import__('os').system('echo pwned')"},
        "transitions": [{"label": "t", "set": {"a": "harmless"}}],
        "invariants": {"c": {"forbid": {"a": "never"}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert r["ok"] is True and r["all_hold"] is True


# --------------------------------------------------------------------------- schema contract
def test_every_declared_tool_is_implemented_and_vice_versa():
    assert {t["name"] for t in TOOL_SCHEMAS} == set(TOOLS)


@pytest.mark.parametrize("schema", TOOL_SCHEMAS, ids=[t["name"] for t in TOOL_SCHEMAS])
def test_each_schema_is_well_formed(schema):
    assert schema["description"]
    assert schema["inputSchema"]["type"] == "object"
    for req in schema["inputSchema"].get("required", []):
        assert req in schema["inputSchema"]["properties"]
