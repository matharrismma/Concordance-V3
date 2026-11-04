"""CONCORDANCE_ALLOW_CODE_EXEC is the real control on computer_science's exec, proved through the route.

computer_science.py says of itself that a restricted namespace is no sandbox, so what stands between a request and
exec is one flag, default off. tests/conftest.py turns it on for the rest of the suite. Here it is off: a code packet
sent through http_api.route runs nothing and is refused. The same packet with the flag on sets the marker, which is
what shows the packet would run. The marker is one attribute on the math module in this test process.
"""
from __future__ import annotations

import json
import math

import pytest

from concordance import http_api

FLAG = "CONCORDANCE_ALLOW_CODE_EXEC"
MARKER = "v3_code_exec_marker"
PACKET = {"CS_VERIFY": {"function_name": "f", "code": f"math.{MARKER} = 1\ndef f():\n    return 1\n",
                        "test_cases": [{"args": [], "expected": 1}]}}


@pytest.fixture(autouse=True)
def _no_marker():
    math.__dict__.pop(MARKER, None)
    yield
    math.__dict__.pop(MARKER, None)


def _post() -> dict:
    body = {"steps": [{"id": "r", "domain": "computer_science", "spec": PACKET}]}
    status, _headers, out = http_api.route("POST", "/verify", {"seal": ["0"]}, body, {}, b"")
    assert status == 200, out
    return json.loads(out)


def test_with_the_flag_off_a_code_packet_runs_nothing_and_is_refused(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    r = _post()
    assert not hasattr(math, MARKER), "the code ran with the flag off"
    assert r["verdict"] not in ("HOLDS", "BROKEN"), r
    assert not r.get("seal")
    assert "disabled" in json.dumps(r["trail"]), r


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "2"])
def test_only_the_exact_value_turns_it_on(monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    r = _post()
    assert not hasattr(math, MARKER), "the code ran"
    assert r["verdict"] not in ("HOLDS", "BROKEN"), r


def test_with_the_flag_on_the_same_packet_runs(monkeypatch):
    """The control: the packet above is live, so its refusal is the flag's doing and nothing else's."""
    monkeypatch.setenv(FLAG, "1")
    assert _post()["verdict"] == "HOLDS"
    assert getattr(math, MARKER) == 1
