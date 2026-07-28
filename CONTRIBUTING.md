# Contributing to minicheck-mcp

A safe, declarative surface between an agent and a decision procedure is the point of this package. That shapes what changes are easy to
accept.

## Ground rules

1. **Specs stay data.** No `eval`, no `exec`, no import of anything a spec names. There is a test
   asserting a code-shaped string stays a string; it must keep passing.
2. **A tool never raises.** `dispatch` returns `{"ok": false, ...}` for every failure mode, because a
   traceback across a transport is a broken session. Add the failing case to the tests.
3. **Every declared tool is implemented, and vice versa.** A test pins `TOOL_SCHEMAS` against `TOOLS`.

## Getting set up

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
```

## Pull requests

- Add a test that fails before your change and passes after. Tests live in `tests/`.
- Keep the public API in `__all__` explicit; anything not listed there is internal.
- New spec syntax needs a validator rule and a rejection test in the same pull request.
- Sign-off by [DCO](https://developercertificate.org/) (`git commit -s`). There is no CLA.

## Reporting a security issue

A spec that causes execution, filesystem access, or a network call is the most serious possible bug
here. Please report it privately first, with the spec that triggers it.
