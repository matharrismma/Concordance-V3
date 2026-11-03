"""tools/check.py is V3's one gate list, and CI's gates job calls it instead of keeping a second list.

It was a byte copy of concordance-2's: it loaded `-p vacuity_plugin` (V3 has none, so it could not start)
and enforced concordance-2's 90% coverage floor, while .github/workflows/ci.yml kept its own list of commands.
These pin the list by name and command, that nothing in it installs, shells out or loads a plugin, that CI
holds no second list, that check.py still takes the floor the harness shares, and that the vocabulary gate's
text.py exemption holds on Windows paths too. They read files and import check.py; no gate is run here.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# The modules the core is entered through, as .github/workflows/ci.yml's closure step listed them at b806017.
ENTRYPOINTS_AT_B806017 = ["derivation", "audit", "receipts", "cas", "ledger", "discern", "capabilities", "redact",
                          "airlock", "tool_registry", "verifiers", "mcp.server", "engine", "http_api", "__main__",
                          "schema", "text", "scribe", "compose", "transparency", "bucket"]


def _check():
    spec = importlib.util.spec_from_file_location("_v3_check", ROOT / "tools" / "check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_py_holds_every_named_gate():
    C = _check()
    gates = {g.name: g for g in C.GATES}
    assert gates["suite"].argv == [PY, "-m", "pytest", "-q"]
    assert gates["benchmark"].argv == [PY, "tools/benchmark.py"]                 # fails on any FP or FN
    assert gates["benchmark --check"].argv == [PY, "tools/benchmark.py", "--check"]
    assert gates["benchmark --json"].argv == [PY, "tools/benchmark.py", "--json"]
    assert gates["benchmark --json"].stdout_file == "benchmark.json"            # what ci.yml uploads
    assert gates["schema_gen --check"].argv == [PY, "tools/schema_gen.py", "--check"]
    assert gates["vocab_gate"].argv == [PY, "tools/vocab_gate.py"]
    assert gates["unreached"].argv == [PY, "tools/unreached.py"]
    assert gates["closure"].argv == [PY, "tools/closure.py", *C.ENTRYPOINTS, "--lazy", "--src", "src/concordance"]
    assert gates["closure"].judge is not None                                   # judged against CORE_MODULES.txt
    assert C.ENTRYPOINTS == ENTRYPOINTS_AT_B806017
    assert gates["ruff"].argv == [PY, "-m", "ruff", "check", "src", "tools", "tests"]
    assert all(g.env["PYTHONPATH"] == str(ROOT / "src") for g in C.GATES)


def test_the_closure_gate_judges_against_core_modules():
    C = _check()
    core = (ROOT / "CORE_MODULES.txt").read_text(encoding="utf-8")
    assert C._within_core(core)[0] is True
    ok, why = C._within_core(core + "not_a_core_module   1  <- derivation\n")
    assert ok is False and "not_a_core_module" in why


def test_the_unreached_gate_fails_when_it_measured_nothing():
    """On Windows unreached.py's path filter once matched no coverage key, and it reported this line and
    exited 0 (measured on this laptop with check.py's first run): a coverage gate that checked nothing."""
    C = _check()
    assert {g.name: g for g in C.GATES}["unreached"].judge is C._measured_something
    vacuous = "0 verify_* functions; 0 reached by the benchmark; 0 unreached (0 with a stated reason, 0 gaps)"
    assert C._measured_something(vacuous + "\n")[0] is False
    assert C._measured_something("no summary at all")[0] is False
    assert C._measured_something("443 verify_* functions; 424 reached by the benchmark; 19 unreached "
                                 "(19 with a stated reason, 0 gaps)\n  x.y  reason\n")[0] is True


def test_no_gate_installs_shells_out_or_loads_a_plugin():
    C = _check()
    for g in C.GATES:
        assert g.argv[0] == PY, g.name
        for banned in ("pip", "-p", "vacuity_plugin", "--fail-under", "&&", "||", ">", "|", ";"):
            assert banned not in g.argv, (g.name, banned)
    src = (ROOT / "tools" / "check.py").read_text(encoding="utf-8")
    assert "vacuity_plugin" not in src and "fail-under" not in src and "shell=True" not in src


def test_ci_gates_job_calls_check_py_and_keeps_no_second_list():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gates_job = ci.split("\n  gates:\n", 1)[1].split("\n  slow:\n", 1)[0]
    assert "run: python tools/check.py" in gates_job
    for second_list in ("pytest", "tools/benchmark.py", "tools/schema_gen.py", "tools/vocab_gate.py",
                        "tools/unreached.py", "tools/closure.py", "CORE_MODULES.txt", "ruff"):
        assert second_list not in gates_job, second_list
    run_lines = [ln.strip() for ln in gates_job.splitlines() if ln.strip().startswith("- run:")]
    assert run_lines == ['- run: pip install -e ".[math,scribe,signing,dev]"',
                         "- run: python tools/check.py   # the one gate list (it writes benchmark.json, uploaded below)"]
    assert gates_job.index("python tools/check.py") < gates_job.index("upload-artifact")
    assert "path: benchmark.json" in gates_job


def test_check_py_takes_and_yields_the_shared_floor(tmp_path, monkeypatch):
    C = _check()
    assert os.path.basename(C.LOCK) == ".gate.lock" and Path(C.LOCK).parent == ROOT   # the harness's lock
    lock = tmp_path / ".gate.lock"
    monkeypatch.setattr(C, "LOCK", str(lock))
    lock.write_text(f"{os.getpid()} harness.py\n", encoding="utf-8")               # a live holder
    assert C._take_the_floor() is False and lock.read_text(encoding="utf-8").startswith(f"{os.getpid()} harness")
    lock.write_text("2147483646 harness.py\n", encoding="utf-8")                    # a dead one: reclaimed
    assert C._take_the_floor() is True
    assert lock.read_text(encoding="utf-8") == f"{os.getpid()} check.py\n"
    C._yield_the_floor()
    assert not lock.exists()
    lock.write_text("2147483646 harness.py\n", encoding="utf-8")                    # never yields another's
    C._yield_the_floor()
    assert lock.exists()


def test_vocab_gate_exempts_text_py_on_every_path_separator():
    p = subprocess.run([PY, "tools/vocab_gate.py"], cwd=str(ROOT), capture_output=True, text=True,
                       env=dict(os.environ, PYTHONPATH=str(ROOT / "src")))
    flagged = [ln for ln in p.stdout.splitlines() if "text.py:" in ln]
    assert flagged == [], flagged
