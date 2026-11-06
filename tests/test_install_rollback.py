"""deploy/install.sh, dry-run: every way a ship can fail puts back the commit and the unit, and leaves data/ and .env alone.

The script runs for real, in bash, against a real git repository with an origin one commit ahead, a fake unit directory
and stubs for pip, python, sudo, systemctl, curl and sleep. Git is real on purpose: what a forced checkout does and does
not reach is the whole of the promise about seals. A stub's log records what was done and in what order. What the box's
systemd does with any of this is not here: the lead proves that once, on the box.

The suite has no time to spare, so the paths that carry the claim run in it and the full matrix of failed steps is behind
`-m slow`, which CI runs on Linux on every push.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "deploy" / "install.sh"
UNIT = ROOT / "deploy" / "nh-v3.service"
OLD_UNIT = "[Service]\nExecStart=old\n"
LIVE_BENCHMARK = '{"live": "what the last ship measured"}\n'

STUBS = {
    # real git, with a way to fail or to be killed at the step that matters
    "git": '''
echo "git $*" >> "$STATE/log"
forced=0; case "$*" in *"checkout -q --force"*) forced=1 ;; esac
case "$*" in *" fetch "*) if [ -e "$STATE/fail_fetch" ]; then rm "$STATE/fail_fetch"; exit 1; fi ;; esac
if [ "$forced" = 1 ]; then
  if [ -e "$STATE/kill_before_force" ]; then rm "$STATE/kill_before_force"; kill -9 "$PPID"; exit 1; fi
  if [ -e "$STATE/fail_force" ]; then rm "$STATE/fail_force"; exit 1; fi
fi
"$REAL_GIT" "$@"; rc=$?
if [ "$forced" = 1 ] && [ -e "$STATE/kill_after_force" ]; then rm "$STATE/kill_after_force"; kill -9 "$PPID"; fi
exit "$rc"
''',
    "sudo": '''
if [ "$1" = "-n" ]; then [ ! -e "$STATE/no_sudo" ]; exit; fi
if [ "$1" = cp ] && [ -e "$STATE/fail_cp" ]; then rm "$STATE/fail_cp"; exit 1; fi
if [ "$1" = cp ] && [ -e "$STATE/fail_cp_back" ] && [ "$(cat "$DEST/CODE")" = old ]; then exit 1; fi
exec "$@"
''',
    "systemctl": '''
echo "systemctl $* code=$(cat "$DEST/CODE" 2>/dev/null)" >> "$STATE/log"
case "$1" in
  show) case "$*" in *MainPID*) cat "$STATE/pid" ;; *NRestarts*) cat "$STATE/restarts" ;; esac ;;
  *) if [ -e "$STATE/fail_$1" ]; then rm "$STATE/fail_$1"; exit 1; fi
     if [ "$1" = restart ] && [ "$(cat "$DEST/CODE")" = old ]; then rm -f "$STATE/new_code_is_silent"; fi ;;
esac
''',
    "curl": '''
echo "curl $*" >> "$STATE/log"
case "$*" in
  *health*)
    n=$(($(cat "$STATE/health_reads") + 1)); echo "$n" > "$STATE/health_reads"
    [ ! -e "$STATE/silent" ] && [ ! -e "$STATE/new_code_is_silent" ] && [ "$n" != "$(cat "$STATE/health_fails_at" 2>/dev/null)" ] ;;
  *capabilities*) if [ -e "$STATE/fail_capabilities" ]; then rm "$STATE/fail_capabilities"; exit 22; fi; echo "{}" ;;
esac
''',
    "sleep": '''
n=$(($(cat "$STATE/slept") + $1)); echo "$n" > "$STATE/slept"
[ -f "$STATE/on_sleep" ] && . "$STATE/on_sleep"
exit 0
''',
    "python3": 'mkdir -p .venv/bin; cp "$STATE/pip" "$STATE/python" .venv/bin/\n',
    "journalctl": "exit 0\n",
}
VENV_PIP = '''
echo "pip $*" >> "$STATE/log"
case "$*" in *"-e "*)
  if [ -e "$STATE/fail_pip" ]; then rm "$STATE/fail_pip"; exit 1; fi
  if [ -e "$STATE/fail_pip_back" ] && [ "$(cat "$DEST/CODE")" = old ]; then exit 1; fi ;;
esac
'''
VENV_PYTHON = '''
echo "python $*" >> "$STATE/log"
case "$*" in
  *"-m pytest"*)
    if [ -e "$STATE/term_during_gates" ]; then rm "$STATE/term_during_gates"; kill -TERM "$PPID"; fi
    if [ -e "$STATE/fail_pytest" ]; then rm "$STATE/fail_pytest"; exit 1; fi ;;
  *benchmark.py*--check*) if [ -e "$STATE/fail_check" ]; then rm "$STATE/fail_check"; exit 1; fi ;;
  *schema_gen.py*--check*) if [ -e "$STATE/fail_schema" ]; then rm "$STATE/fail_schema"; exit 1; fi ;;
  *"--json"*) cp "data/benchmark_last.json" "$STATE/benchmark_during_the_gate"
              echo '{"fresh": "half of an answer'
              if [ -e "$STATE/fail_json" ]; then rm "$STATE/fail_json"; exit 1; fi
              echo '"}' ;;
  *) cat > /dev/null; echo "   up: stub" ;;
esac
'''


def bash() -> str:
    """Git's bash on Windows, never the WSL launcher in system32, which needs a distribution this laptop does not have."""
    candidates = [r"C:\Program Files\Git\bin\bash.exe"] if os.name == "nt" else []
    found = [c for c in (*candidates, shutil.which("bash")) if c and os.path.exists(c)]
    assert found, "this test needs bash"
    return found[0]


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def remove(path: Path) -> None:
    """A checkout, including git's read-only objects, which Windows will not delete as they stand."""
    for item in path.rglob("*"):
        item.chmod(stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    shutil.rmtree(path)


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    """A checkout at the old commit, and an origin one commit ahead that changes the code, the unit, tracked data, the
    benchmark file and the dependencies, so that each of them has to go back."""
    home = tmp_path_factory.mktemp("box") / "home"
    work = home / "concordance-3"
    work.mkdir(parents=True)
    git(home, "init", "-q", "--bare", "--template=", "origin.git")
    git(work, "init", "-q", "--template=", "-b", "main")
    git(work, "config", "core.autocrlf", "false")
    git(work, "remote", "add", "origin", "../origin.git")
    put(work / ".gitignore", "data/cas/\ndata/ledger/\n")
    new_unit = UNIT.read_text(encoding="utf-8").replace("\r\n", "\n")

    def commit(code, unit, golden, benchmark, deps):
        put(work / "CODE", code)
        put(work / "deploy" / "nh-v3.service", unit)
        put(work / "data" / "goldens" / "a.json", golden)
        put(work / "data" / "benchmark_last.json", benchmark)
        put(work / "pyproject.toml", deps)
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", code.strip())
        return git(work, "rev-parse", "HEAD")

    old = commit("old\n", OLD_UNIT, '{"golden": "old"}\n', '{"tracked": "old"}\n', "deps = 1\n")
    commit("new\n", new_unit, '{"golden": "new"}\n', '{"tracked": "new"}\n', "deps = 2\n")
    git(work, "push", "-q", "origin", "main")
    git(work, "reset", "-q", "--hard", old)
    return home


class Box:
    """One fake box. `state` holds what the stubs read and the log they write."""

    def __init__(self, template: Path, tmp: Path, previous_unit: bool = True):
        self.home = tmp / "home"
        shutil.copytree(template, self.home)
        self.state, self.bin, self.units = tmp / "state", tmp / "bin", tmp / "units"
        self.dest = self.home / "concordance-3"
        self.record, self.unit = Path(f"{self.dest}.ship"), self.units / "nh-v3.service"
        for d in (self.state, self.bin, self.units, self.dest / ".venv" / "bin"):
            d.mkdir(parents=True)
        for name, body in STUBS.items():
            self._stub(self.bin / name, body)
        for where in (self.dest / ".venv" / "bin", self.state):
            self._stub(where / "pip", VENV_PIP)
            self._stub(where / "python", VENV_PYTHON)
        # what lives on the box and in no commit
        put(self.dest / "data" / "cas" / "seal-1.json", '{"sealed": 1}\n')
        put(self.dest / "data" / "ledger" / "chain.jsonl", '{"link": 1}\n')
        put(self.dest / "data" / "activity.jsonl", '{"seen": 1}\n')
        put(self.dest / ".env", "CONCORDANCE_ISSUER_KEY=kept\n")
        put(self.dest / "data" / "benchmark_last.json", LIVE_BENCHMARK)     # as the last ship left it, differing from git
        if previous_unit:
            put(self.unit, OLD_UNIT)
        self.old_sha = self.head()
        self.new_unit = UNIT.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.reset()
        self.script = tmp / "install.sh"        # a checkout on Windows is CRLF, which bash cannot read
        put(self.script, INSTALL.read_text(encoding="utf-8").replace("\r\n", "\n"))

    def _stub(self, path: Path, body: str) -> None:
        put(path, "#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def reset(self) -> None:
        for name, text in (("pid", "100"), ("restarts", "0"), ("slept", "0"), ("health_reads", "0")):
            self.set(name, text)
        (self.state / "on_sleep").unlink(missing_ok=True)

    def set(self, name: str, text: str = "") -> None:
        put(self.state / name, text)

    def head(self) -> str:
        return git(self.dest, "rev-parse", "HEAD")

    def code(self) -> str:
        return (self.dest / "CODE").read_text(encoding="utf-8")

    def kept(self) -> dict:
        """Every byte of data/ and .env."""
        files = [p for p in (self.dest / "data").rglob("*") if p.is_file()] + [self.dest / ".env"]
        return {p.relative_to(self.dest).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

    def seals(self) -> dict:
        """What no commit holds: the bytes git cannot give back."""
        return {k: v for k, v in self.kept().items() if k in ("data/cas/seal-1.json", "data/ledger/chain.jsonl",
                                                             "data/activity.jsonl", ".env")}

    def benchmark(self) -> str:
        return (self.dest / "data" / "benchmark_last.json").read_text(encoding="utf-8")

    def run(self, hold_s=3, ref="main") -> subprocess.CompletedProcess:
        env = dict(os.environ, DEST=self.dest.as_posix(), STATE=self.state.as_posix(), UNIT_DIR=self.units.as_posix(),
                   REF=ref, PORT="8020", REPO=(self.home / "origin.git").as_posix())
        env.pop("HOLD_S", None)
        if hold_s is not None:
            env["HOLD_S"] = str(hold_s)
        # the stubs go first from inside bash: Git's bash on Windows puts its own directories ahead of what it inherits
        first = ('stubs="$1"; if command -v cygpath >/dev/null; then stubs="$(cygpath -u "$1")"; fi; '
                 'REAL_GIT="$(command -v git)" PATH="$stubs:$PATH" exec bash "$2"')
        return subprocess.run([bash(), "-c", first, "stubs", self.bin.as_posix(), self.script.as_posix()],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)

    @property
    def log(self) -> str:
        return (self.state / "log").read_text(encoding="utf-8") if (self.state / "log").exists() else ""


@pytest.fixture
def box(template, tmp_path):
    return Box(template, tmp_path)


def rolled_back(box: Box, done: subprocess.CompletedProcess, before: dict, code=1) -> None:
    """What every failure must leave: the old commit and unit, the service restarted on them and reporting, the record
    gone, and every byte of data/ and .env as it was."""
    assert code is None or done.returncode == code, done.stdout + done.stderr
    assert box.head() == box.old_sha and box.code() == "old\n"
    assert box.unit.read_text(encoding="utf-8") == OLD_UNIT
    assert box.kept() == before
    assert not box.record.exists()
    assert "/health answers" in done.stdout
    assert re.search(r"systemctl restart nh-v3 code=old$", box.log, re.M)


def fails_the_same_twice(box: Box, arrange) -> None:
    before = box.kept()
    for _ in (1, 2):
        box.reset()
        arrange()
        rolled_back(box, box.run(), before)


# ── a ship that holds ────────────────────────────────────────────────────────────────────────────────
def test_a_ship_that_holds_keeps_the_record_until_past_the_watchdog_and_twice_is_the_same(box):
    seals = box.seals()
    box.set("on_sleep", '[ -e "$DEST.ship/sha" ] && echo "$n" >> "$STATE/record_held"\n')
    done = box.run(hold_s=None)
    assert done.returncode == 0, done.stdout + done.stderr
    watchdog_s = int(re.search(r"^WatchdogSec=(\d+)", box.new_unit, re.M).group(1))
    held = (box.state / "record_held").read_text(encoding="utf-8").split()
    assert int(held[-1]) > watchdog_s                   # slept past WatchdogSec with the record still there
    assert not box.record.exists()                      # and only then was it gone
    assert box.code() == "new\n" and box.head() != box.old_sha
    assert box.unit.read_text(encoding="utf-8") == box.new_unit
    assert box.seals() == seals
    assert box.benchmark() == '{"fresh": "half of an answer\n"}\n'      # the finished run's own bytes
    box.reset()
    again = box.run()
    assert again.returncode == 0, again.stdout + again.stderr           # the file the last ship wrote blocks nothing
    assert box.seals() == seals and box.code() == "new\n"


# ── a service that answers and then fails ────────────────────────────────────────────────────────────
def test_a_restart_during_the_hold_rolls_back_and_what_was_written_during_it_survives(box):
    before = box.kept()
    box.set("on_sleep", '''
if [ "$n" = 5 ]; then
  echo written > "$DEST/data/cas/seal-during-hold"
  echo more >> "$DEST/.env"
  echo 1 > "$STATE/restarts"
fi
''')
    done = box.run(hold_s=10)
    assert done.returncode == 1, done.stdout + done.stderr
    assert box.head() == box.old_sha and box.unit.read_text(encoding="utf-8") == OLD_UNIT
    assert (box.dest / "data" / "cas" / "seal-during-hold").read_text(encoding="utf-8") == "written\n"
    assert (box.dest / ".env").read_text(encoding="utf-8") == "CONCORDANCE_ISSUER_KEY=kept\nmore\n"
    still = {k: v for k, v in box.kept().items() if k not in ("data/cas/seal-during-hold", ".env")}
    assert still == {k: v for k, v in before.items() if k != ".env"}


# ── a failed gate ────────────────────────────────────────────────────────────────────────────────────
def test_a_failed_benchmark_gate_leaves_the_file_as_it_was(box):
    box.set("fail_json")
    rolled_back(box, box.run(), box.kept())
    assert box.benchmark() == LIVE_BENCHMARK            # not emptied, not half of an answer, not git's copy
    assert (box.state / "benchmark_during_the_gate").read_text(encoding="utf-8") == LIVE_BENCHMARK  # nor while it ran


def test_a_failed_service_step_puts_the_unit_back(box):
    fails_the_same_twice(box, lambda: box.set("fail_restart"))


# ── an interrupted rollback ──────────────────────────────────────────────────────────────────────────
def test_a_rollback_killed_after_its_checkout_loses_nothing_and_the_next_run_stands(box):
    seals = box.seals()
    box.set("fail_pytest")
    box.set("kill_after_force")
    done = box.run()
    assert done.returncode not in (0, 1, 3)             # it did not finish, and said nothing
    assert box.seals() == seals                         # a kill cannot reach what the rollback never touches
    assert (box.record / "sha").read_text(encoding="utf-8").strip() == box.old_sha
    assert box.benchmark() == '{"tracked": "old"}\n'    # the one window: git's copy, valid, until the next run
    box.reset()
    done = box.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert box.seals() == seals and box.code() == "new\n" and not box.record.exists()


def test_a_run_after_an_interrupted_one_goes_back_to_what_the_first_recorded(box):
    before = box.kept()
    box.set("fail_restart")
    box.set("kill_before_force")
    assert box.run().returncode not in (0, 1, 3)
    assert box.code() == "new\n" and box.unit.read_text(encoding="utf-8") == box.new_unit      # stranded, seals and all
    box.reset()
    box.set("fail_pytest")
    rolled_back(box, box.run(), before)                 # the record said old, whatever HEAD said


# ── a rollback that cannot finish ────────────────────────────────────────────────────────────────────
def test_a_rollback_that_cannot_check_out_says_so_and_keeps_its_record(box):
    before = box.kept()
    box.set("fail_pytest")
    box.set("fail_force")
    done = box.run()
    assert done.returncode == 3, done.stdout + done.stderr
    assert "a human must look" in done.stdout and "rolled back" not in done.stdout
    assert (box.record / "sha").exists() and box.seals() == {k: before[k] for k in box.seals()}
    box.reset()
    box.set("fail_pytest")
    rolled_back(box, box.run(), before)                 # and the next run can still finish the job


def test_tracked_data_changed_by_hand_stops_the_ship_before_anything_moves(box):
    put(box.dest / "data" / "goldens" / "a.json", '{"golden": "edited on the box"}\n')
    before = box.kept()
    done = box.run()
    assert done.returncode == 3, done.stdout + done.stderr
    assert box.kept() == before and box.head() == box.old_sha and not box.record.exists()
    assert " fetch -q" not in box.log


# ── the matrix, behind -m slow ───────────────────────────────────────────────────────────────────────
@pytest.mark.slow
@pytest.mark.parametrize("flag", ["fail_fetch", "fail_pip", "fail_pytest", "fail_check", "fail_schema", "fail_json", "fail_cp",
                                  "fail_daemon-reload", "fail_enable", "new_code_is_silent", "fail_capabilities"])
def test_each_failed_step_rolls_back_twice_over(box, flag):
    fails_the_same_twice(box, lambda: box.set(flag))


@pytest.mark.slow
@pytest.mark.parametrize("name,text", [("pid", "0"), ("health_fails_at", "2")])
def test_each_failed_hold_rolls_back_twice_over(box, name, text):
    fails_the_same_twice(box, lambda: box.set(name, text))


@pytest.mark.slow
@pytest.mark.parametrize("change", ['echo 200 > "$STATE/pid"', 'echo 1 > "$STATE/restarts"'])
def test_a_change_during_the_hold_rolls_back_twice_over(box, change):
    fails_the_same_twice(box, lambda: box.set("on_sleep", f'[ "$n" = 5 ] && {change}\n'))


@pytest.mark.slow
def test_a_rollback_killed_before_its_checkout_leaves_the_benchmark_file_as_it_was(box):
    seals = box.seals()
    box.set("fail_pytest")
    box.set("kill_before_force")
    assert box.run().returncode not in (0, 1, 3)
    assert box.benchmark() == LIVE_BENCHMARK and box.seals() == seals


@pytest.mark.slow
def test_a_ref_that_does_not_exist_rolls_back(box):
    before = box.kept()
    rolled_back(box, box.run(ref="no-such-ref"), before)


@pytest.mark.slow
def test_a_term_during_the_gates_rolls_back(box):
    before = box.kept()
    box.set("term_during_gates")
    done = box.run()
    assert done.returncode != 0                         # bash raises the signal again after its EXIT trap, so no exit code
    rolled_back(box, done, before, code=None)


@pytest.mark.slow
@pytest.mark.parametrize("flag,says", [("fail_restart", "did not restart"), ("silent", "does not answer"),
                                       ("fail_pip_back", "reinstall failed"), ("fail_cp_back", "could not put the unit back"),
                                       ("fail_daemon-reload", "daemon-reload failed")])
def test_each_failed_step_of_a_rollback_says_so_and_loses_nothing(box, flag, says):
    seals = box.seals()
    box.set("fail_pytest")
    box.set(flag)
    done = box.run()
    assert done.returncode == 3, done.stdout + done.stderr
    assert says in done.stdout and "a human must look" in done.stdout
    assert box.seals() == seals and (box.record / "sha").exists()


@pytest.mark.slow
def test_with_no_previous_unit_the_new_one_is_taken_away(template, tmp_path):
    box = Box(template, tmp_path, previous_unit=False)
    before = box.kept()
    box.set("fail_restart")
    done = box.run()
    assert done.returncode == 1, done.stdout + done.stderr
    assert not box.unit.exists() and box.code() == "old\n" and box.kept() == before


@pytest.mark.slow
def test_with_no_sudo_nothing_is_restarted_and_nothing_is_held(template, tmp_path):
    box = Box(template, tmp_path)
    seals = box.seals()
    shutil.rmtree(box.units)
    box.set("no_sudo")
    done = box.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "systemctl restart" not in box.log and "-p MainPID" not in box.log
    assert box.code() == "new\n" and not box.record.exists() and box.seals() == seals


@pytest.mark.slow
def test_a_first_install_clones_and_finishes(template, tmp_path):
    box = Box(template, tmp_path, previous_unit=False)
    remove(box.dest)
    done = box.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert box.code() == "new\n" and box.unit.exists() and not box.record.exists()


@pytest.mark.slow
def test_a_first_install_that_fails_keeps_its_checkout_and_takes_its_unit_away(template, tmp_path):
    box = Box(template, tmp_path, previous_unit=False)
    remove(box.dest)
    box.set("fail_restart")
    done = box.run()
    assert done.returncode == 1, done.stdout + done.stderr
    assert box.dest.is_dir() and not box.unit.exists() and not box.record.exists()
