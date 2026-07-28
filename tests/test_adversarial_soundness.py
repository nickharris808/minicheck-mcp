"""Adversarial contract suite for the agent-facing surface.

This is the highest-stakes surface in the portfolio. A human reading a verdict brings judgement; an
agent reads a JSON field and acts. So the contract has to be unambiguous under every failure mode:

    * ``ok: false`` means NO verdict was produced. It never implies anything about the spec.
    * ``all_hold``/``holds`` are three-valued — ``true``, ``false``, ``null`` — and ``null`` is
      never a pass.
    * Both keys are ALWAYS present, so an agent reading them cannot mistake an absent key for a
      negative answer.

The last point is the shipped defect: `dispatch` returned bare ``{"ok": false, ...}`` on any
exception, so ``result.get("all_hold")`` was ``None`` — indistinguishable from a real undetermined
verdict, and falsy exactly like a refutation.
"""

from __future__ import annotations

import json

import pytest

from minicheck_mcp.server import TOOL_SCHEMAS, TOOLS, dispatch

SAFE_SPEC = {
    "fields": ["a", "b"],
    "initial": {"a": 0, "b": 0},
    "transitions": [
        {"label": "a1", "when": {"a": 0, "b": 0}, "set": {"a": 1}},
        {"label": "a0", "when": {"a": 1}, "set": {"a": 0}},
    ],
    "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}},
}

BROKEN_SPEC = {
    "fields": ["a", "b"],
    "initial": {"a": 0, "b": 0},
    "transitions": [
        {"label": "a1", "when": {"a": 0}, "set": {"a": 1}},
        {"label": "b1", "when": {"b": 0}, "set": {"b": 1}},
    ],
    "invariants": {"not_both": {"forbid": {"a": 1, "b": 1}}},
}

UNBOUNDED_SPEC = {
    "fields": ["c"],
    "initial": {"c": 0},
    "transitions": [{"label": "inc", "set": {"c": {"incr": 1}}}],
    "invariants": {"never_neg": {"forbid": {"c": -5}}},
}


def assert_verdict_contract(result):
    """The invariant every response must satisfy, whatever went wrong."""
    assert isinstance(result, dict)
    assert result["ok"] in (True, False)
    if result["ok"] is False:
        # An error must be unmistakable, and must carry the verdict keys explicitly so that an
        # agent reading them sees "no answer" rather than a falsy pass.
        assert "all_hold" in result, "error response omits all_hold; agents read this key"
        assert result["all_hold"] is None
        assert result["holds"] is None
        assert result["verdict"] == "ERROR"
        assert isinstance(result["message"], str) and result["message"]
    else:
        if "all_hold" in result:
            assert result["all_hold"] in (True, False, None)
        if "holds" in result:
            assert result["holds"] in (True, False, None)


# ------------------------------------------------------------------- C1 through the agent surface
def test_the_clamp_false_proof_is_dead_on_the_agent_surface():
    """The published Space and any connected agent both reach this code path."""
    spec = {
        "fields": ["c"],
        "initial": {"c": 0},
        "transitions": [{"label": "inc", "set": {"c": {"incr": 1}}}],
        "invariants": {"never_100": {"forbid": {"c": 100}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert r.get("all_hold") is not True
    assert_verdict_contract(r)


def test_an_incomplete_search_says_so_loudly():
    r = dispatch("check_invariant", {"spec": UNBOUNDED_SPEC})
    assert r["ok"] is True
    assert r["exhaustive"] is False
    assert r["all_hold"] is None
    assert r["verdict"] == "UNDETERMINED"
    assert "int_bound" in r["incomplete_reason"]
    assert "advice" in r
    assert_verdict_contract(r)


def test_a_genuine_proof_is_still_reported_as_one():
    r = dispatch("check_invariant", {"spec": SAFE_SPEC})
    assert r["all_hold"] is True
    assert r["verdict"] == "PROVED"
    assert r["exhaustive"] is True
    assert_verdict_contract(r)


def test_a_genuine_refutation_carries_a_replayable_trace():
    r = dispatch("check_invariant", {"spec": BROKEN_SPEC})
    assert r["all_hold"] is False
    assert r["verdict"] == "REFUTED"
    cex = r["invariants"]["not_both"]["counterexample"]
    assert cex[0]["state"] == {"a": 0, "b": 0}
    assert cex[-1]["state"]["a"] == 1 and cex[-1]["state"]["b"] == 1
    assert_verdict_contract(r)


def test_refuted_beats_undetermined_when_both_are_present():
    """One proved, one refuted, one undetermined -> the aggregate must be REFUTED, not UNDETERMINED."""
    spec = {
        "fields": ["c"],
        "initial": {"c": 0},
        "transitions": [{"label": "inc", "set": {"c": {"incr": 1}}}],
        "invariants": {"never_5": {"forbid": {"c": 5}}, "never_neg": {"forbid": {"c": -3}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert r["invariants"]["never_5"]["holds"] is False
    assert r["invariants"]["never_neg"]["holds"] is None
    assert r["all_hold"] is False  # a definite refutation dominates


def test_a_trivial_invariant_is_flagged_as_trivial():
    """`holds: true` for a value the space cannot represent must not read as verification."""
    spec = {
        "fields": ["x"],
        "initial": {"x": 0},
        "transitions": [{"label": "t", "when": {"x": 0}, "set": {"x": 1}}],
        "invariants": {"impossible": {"forbid": {"x": 9999}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert r["all_hold"] is True
    assert "warnings" in r
    assert "trivially satisfied" in r["warnings"][0]


# ------------------------------------------------------------------------- C7: errors as verdicts
@pytest.mark.parametrize(
    "args",
    [
        {},
        {"spec": None},
        {"spec": "a string"},
        {"spec": []},
        {"spec": 42},
        {"spec": {}},
        {"spec": {"fields": []}},
        {"spec": {"fields": ["a"], "initial": {"a": 0}}},
        {"spec": {"fields": ["a"], "initial": {"a": 0}, "transitions": [], "invariants": {}}},
        {"spec": SAFE_SPEC, "invariant": "no_such_invariant"},
        {"spec": SAFE_SPEC, "unexpected_kwarg": 1},
        {"wrong": 1},
    ],
)
def test_every_bad_call_returns_the_error_contract(args):
    r = dispatch("check_invariant", args)
    assert r["ok"] is False
    assert_verdict_contract(r)


@pytest.mark.parametrize("tool", ["check_invariant", "check_liveness", "validate_spec", "spec_help"])
@pytest.mark.parametrize("args", [{}, {"spec": None}, {"spec": 1}, {"spec": {"fields": 1}}, {"garbage": True}, None])
def test_no_tool_ever_raises(tool, args):
    """The transport must survive anything. Every tool, every malformed argument shape."""
    r = dispatch(tool, args)
    assert isinstance(r, dict)
    assert_verdict_contract(r)


def test_unknown_tool_keeps_its_stable_error_code():
    r = dispatch("no_such_tool", {})
    assert r["ok"] is False
    assert r["error"] == "UnknownTool"
    assert_verdict_contract(r)


def test_bad_arguments_keep_their_stable_error_code():
    r = dispatch("check_invariant", {"wrong_kwarg": 1})
    assert r["ok"] is False
    assert r["error"] == "BadArguments"
    assert_verdict_contract(r)


def test_non_dict_arguments_are_refused():
    for args in ("string", 42, [1, 2]):
        r = dispatch("check_invariant", args)
        assert r["ok"] is False
        assert_verdict_contract(r)


def test_liveness_without_a_goal_is_an_error_not_a_pass():
    r = dispatch("check_liveness", {"spec": SAFE_SPEC})
    assert r["ok"] is False
    assert r["holds"] is None
    assert "goal" in r["message"]
    assert_verdict_contract(r)


# ----------------------------------------------------------------------- no code execution, ever
@pytest.mark.parametrize(
    "payload",
    [
        {"__class__": "x"},
        {"fields": ["__import__('os').system('echo pwned')"], "initial": {}, "transitions": []},
        {"fields": ["a"], "initial": {"a": "__import__('os')"}, "transitions": [{"set": {"a": 1}}]},
        {"fields": ["a"], "initial": {"a": 0}, "transitions": [{"label": "eval('1')", "set": {"a": 1}}]},
        {"fields": ["a"], "initial": {"a": 0}, "transitions": [{"set": {"a": {"incr": "__import__"}}}]},
    ],
)
def test_a_spec_is_data_and_is_never_executed(payload):
    """Nothing in a spec reaches eval/exec. The worst case is a SpecError."""
    r = dispatch("check_invariant", {"spec": payload})
    assert isinstance(r, dict)
    assert_verdict_contract(r)


def test_deeply_nested_payload_does_not_blow_the_stack():
    nested: dict = {"a": 1}
    for _ in range(2000):
        nested = {"nest": nested}
    r = dispatch("check_invariant", {"spec": nested})
    assert r["ok"] is False
    assert_verdict_contract(r)


def test_huge_field_count_is_bounded_not_hung():
    """200 boolean fields is 2^200 states; the cap must stop it rather than the machine."""
    fields = [f"f{i}" for i in range(200)]
    spec = {
        "fields": fields,
        "initial": dict.fromkeys(fields, 0),
        "transitions": [{"label": f"set{f}", "when": {f: 0}, "set": {f: 1}} for f in fields],
        "invariants": {"never": {"forbid": {fields[0]: 99}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert_verdict_contract(r)
    # Whatever happens, it must not claim a proof it did not perform.
    if r["ok"]:
        assert not (r["all_hold"] is True and r["exhaustive"] is False)


def test_unicode_and_control_characters_survive_a_round_trip():
    spec = {
        "fields": ["état"],
        "initial": {"état": 0},
        "transitions": [{"label": "🚀\x00", "when": {"état": 0}, "set": {"état": 1}}],
        "invariants": {"ok\n": {"forbid": {"état": 1}}},
    }
    r = dispatch("check_invariant", {"spec": spec})
    assert_verdict_contract(r)
    json.dumps(r, default=str)  # must remain serialisable for the transport


# ------------------------------------------------------------------------------ schema/tool wiring
def test_every_declared_tool_exists_and_every_tool_is_declared():
    declared = {t["name"] for t in TOOL_SCHEMAS}
    assert declared == set(TOOLS), "TOOL_SCHEMAS and TOOLS have drifted apart"


def test_every_schema_is_wellformed():
    for t in TOOL_SCHEMAS:
        assert isinstance(t["description"], str) and len(t["description"]) > 20
        assert t["inputSchema"]["type"] == "object"
        json.dumps(t)


def test_the_check_invariant_description_states_the_three_valued_contract():
    """An agent reads this string to decide how to interpret the result. It has to be right."""
    desc = next(t for t in TOOL_SCHEMAS if t["name"] == "check_invariant")["description"]
    assert "null" in desc
    assert "NOT a pass" in desc or "not a pass" in desc


def test_spec_help_no_longer_claims_integers_are_clamped():
    """The help text said 'Integers are clamped', which described the bug rather than the fix."""
    r = dispatch("spec_help")
    assert r["ok"] is True
    assert "clamped" not in r["format"]
    assert "int_bound" in r["format"]
    assert "UNDETERMINED" in r["format"]


def test_spec_help_example_is_actually_correct():
    """The worked example ships a verdict; that verdict must be the one the checker produces."""
    r = dispatch("spec_help")
    example_result = r["example_result"]
    recomputed = dispatch("check_invariant", {"spec": r["example"]})
    assert example_result["all_hold"] == recomputed["all_hold"]
    assert example_result["verdict"] == recomputed["verdict"]


def test_results_are_json_serialisable_for_every_shape():
    for spec in (SAFE_SPEC, BROKEN_SPEC, UNBOUNDED_SPEC, {}, None):
        for tool in ("check_invariant", "check_liveness", "validate_spec"):
            json.dumps(dispatch(tool, {"spec": spec}), default=str)
