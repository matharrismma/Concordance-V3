"""Registration: python -m concordance notary register|retire|list|verify, and deploy/notary_register.sh around it.

Every test works in a temporary data directory with keys made here. The script runs for real, in bash, against a stub
root: stubs for systemctl (which answers for a made-up unit) and sudo (which records the user and runs the command), so
the CLI it calls is this checkout's own, run by this interpreter. What the box's systemd does is not here.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from concordance import notary
from concordance.__main__ import main

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPT = ROOT / "deploy" / "notary_register.sh"
T0 = 1_800_000_000
AT = "2027-01-15T07:59:30Z"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def sha(text) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


class Store:
    def __init__(self, name: str):
        self.name = name
        self.key = Ed25519PrivateKey.generate()
        self.public = b64u(raw_public(self.key))

    def body(self, seq: int, head: str = None) -> bytes:
        head = head or sha(f"{self.name} record {seq}")
        msg = ("concordance-notary-request/v1\n" + self.name + "\n" + str(seq) + "\n" + head + "\n" + AT + "\n").encode()
        return json.dumps({"store": self.name, "seq": seq, "head": head, "at": AT,
                           "sig": b64u(self.key.sign(msg))}).encode("utf-8")


class Clock:
    def __init__(self):
        self.now = float(T0)

    def __call__(self):
        return self.now


def tree(root: Path) -> dict:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): ("dir" if p.is_dir() else (p.stat().st_size,
                                                                       hashlib.sha256(p.read_bytes()).hexdigest()))
            for p in sorted(root.rglob("*"))}


@pytest.fixture
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(d))
    return d


@pytest.fixture
def issuer(monkeypatch):
    key = Ed25519PrivateKey.generate()
    seed = b64u(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()))
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", seed)              # generated for this test, never a real key
    return b64u(raw_public(key))


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(notary, "clock", c)
    return c


def cli(capsys, *argv) -> tuple:
    code = main(["notary", *argv])
    out = capsys.readouterr()
    return code, out.out + out.err


def db_of(data: Path) -> Path:
    return data / "notary" / "notary.db"


# ── register ─────────────────────────────────────────────────────────────────────────────────────────
def test_register_creates_the_folder_and_the_file_in_one_transaction_and_prints_its_absolute_path(data, clock, capsys):
    s = Store("store-a")
    assert tree(data) == {}
    code, out = cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))
    assert code == 0, out
    assert str(db_of(data).resolve()) in out and "ed25519:" + hashlib.sha256(raw_public(s.key)).hexdigest()[:16] in out
    assert sorted(tree(data)) == ["notary", "notary/notary.db"]
    con = sqlite3.connect(db_of(data).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        row = con.execute("SELECT name, public_key, status, registered_at, retired_at, receipts, conflicts_total, "
                          "last_event_at FROM stores").fetchall()
    finally:
        con.close()
    assert row == [("store-a", s.public, "registered", "2027-01-15T08:00:00Z", None, 0, 0, None)]


def test_the_data_dir_is_the_flag_or_the_variable_and_is_never_guessed(tmp_path, monkeypatch, capsys, clock):
    s = Store("store-a")
    monkeypatch.delenv("CONCORDANCE_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    code, out = cli(capsys, "register", "store-a", s.public)
    assert code == 2 and "--data-dir" in out and "CONCORDANCE_DATA_DIR" in out
    assert tree(tmp_path) == {}                                        # no data/ made where the command happened to run
    code, out = cli(capsys, "register", "store-a", s.public, "--data-dir", str(tmp_path / "missing"))
    assert code == 1 and "does not exist" in out and tree(tmp_path) == {}
    (tmp_path / "d").mkdir()
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(tmp_path / "d"))
    code, out = cli(capsys, "register", "store-a", s.public)
    assert code == 0 and str((tmp_path / "d" / "notary" / "notary.db").resolve()) in out


def test_register_refuses_a_name_or_a_key_outside_its_form_and_writes_nothing(data, clock, capsys):
    good = Store("store-a").public
    lenient = good[:-1] + ALPHABET[ALPHABET.index(good[-1]) ^ 1]        # the same 32 bytes to a lenient decoder
    assert base64.urlsafe_b64decode(lenient + "=") == base64.urlsafe_b64decode(good + "=")
    refused = [(name, good) for name in ("ab", "Store-a", "-store-a", "store_a", "store-a\n", "s" * 64, "", "st\u00f6re")]
    refused += [("store-a", key) for key in (good + "=", good[:42], good + "A", good.replace(good[0], "+", 1),
                                             lenient, "", "x" * 43 + "\n")]
    before = tree(data)
    for name, key in refused:
        code, out = cli(capsys, "register", name, key, "--data-dir", str(data))
        assert code == 1, (name, key, out)
        assert tree(data) == before, (name, key)
    for name in ("abc", "a-b", "0-0", "z" * 63):
        assert cli(capsys, "register", name, Store(name).public, "--data-dir", str(data))[0] == 0, name


def test_a_name_is_never_bound_to_a_second_key_even_after_it_is_retired(data, clock, capsys):
    s, other = Store("store-a"), Store("store-a")
    assert cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))[0] == 0
    before = tree(data)
    code, out = cli(capsys, "register", "store-a", other.public, "--data-dir", str(data))
    assert code == 1 and "already" in out and tree(data) == before
    assert cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))[0] == 1    # not even the same key
    assert cli(capsys, "retire", "store-a", "--data-dir", str(data))[0] == 0
    before = tree(data)
    code, out = cli(capsys, "register", "store-a", other.public, "--data-dir", str(data))
    assert code == 1 and "retired" in out and tree(data) == before


# ── retire ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_retirement_is_seen_at_once_and_keeps_the_receipts(data, issuer, clock, capsys):
    s = Store("store-a")
    cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))
    status, _, first = notary.post(s.body(1))
    assert status == 200
    code, out = cli(capsys, "retire", "store-a", "--data-dir", str(data))
    assert code == 0 and str(db_of(data).resolve()) in out
    clock.now += 60
    before = tree(data)
    status, _, out = notary.post(s.body(2))                           # the next request reads the table: no restart
    assert status == 403 and "not registered" in json.loads(out)["error"] and tree(data) == before
    assert notary.post(s.body(1))[0] == 403                           # nor a retry: the name takes nothing now
    assert notary.route("GET", "/notary/stores/store-a/1", "", b"")[2] == first
    st = json.loads(notary.route("GET", "/notary/stores/store-a", "", b"")[2])
    assert st["status"] == "retired" and st["receipts"] == 1
    assert cli(capsys, "retire", "store-a", "--data-dir", str(data))[0] == 1      # already retired
    assert cli(capsys, "retire", "store-b", "--data-dir", str(data))[0] == 1      # never registered
    assert tree(data) == before


# ── list and verify read only ────────────────────────────────────────────────────────────────────────
def test_list_and_verify_with_no_notary_folder_or_no_file_create_nothing(data, issuer, capsys):
    for setup in ("no folder", "a folder and no file"):
        if setup == "a folder and no file":
            (data / "notary").mkdir()
        before = tree(data)
        code, out = cli(capsys, "list", "--data-dir", str(data))
        assert code == 0 and "no store" in out and str(db_of(data).resolve()) in out, out
        code, out = cli(capsys, "verify", "store-a", "--key", issuer, "--data-dir", str(data))
        assert code == 1 and "store-a" in out, out
        assert tree(data) == before, setup


def test_list_shows_every_store_and_reads_only(data, issuer, clock, capsys):
    a, b = Store("store-a"), Store("store-b")
    for s in (a, b):
        cli(capsys, "register", s.name, s.public, "--data-dir", str(data))
    notary.post(a.body(1))
    cli(capsys, "retire", "store-b", "--data-dir", str(data))
    before = tree(data)
    code, out = cli(capsys, "list", "--data-dir", str(data))
    assert code == 0 and tree(data) == before
    lines = [ln for ln in out.splitlines() if ln.startswith("store-")]
    assert len(lines) == 2
    assert "registered" in lines[0] and "receipts=1" in lines[0] and a.public in lines[0]
    assert "retired" in lines[1] and "receipts=0" in lines[1]


def test_verify_walks_a_good_store_and_names_the_first_receipt_that_fails(data, issuer, clock, capsys, monkeypatch):
    s = Store("store-a")
    cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))
    for seq in (3, 1, 2):
        assert notary.post(s.body(seq))[0] == 200
        clock.now += 60
    code, out = cli(capsys, "verify", "store-a", "--key", issuer, "--data-dir", str(data))
    assert code == 0 and "3 receipts" in out, out
    code, out = cli(capsys, "verify", "store-a", "--data-dir", str(data))        # the key from CONCORDANCE_ISSUER_KEY
    assert code == 0, out
    code, out = cli(capsys, "verify", "store-a", "--key", s.public, "--data-dir", str(data))
    assert code == 1 and "n=1" in out and "kid" in out, out
    db = db_of(data)

    def tamper(sql, *params):
        con = sqlite3.connect(str(db), isolation_level=None)
        try:
            if params:
                con.execute(sql, params)
            else:
                con.executescript(sql)
        finally:
            con.close()
    con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        original = con.execute("SELECT n, receipt, hash FROM receipts ORDER BY n").fetchall()
    finally:
        con.close()
    r2 = json.loads(original[1][1])
    breaks = [
        ("UPDATE receipts SET receipt = ? WHERE n = 2", (json.dumps(dict(r2, head=sha("rewritten"))),), "n=2"),
        ("UPDATE receipts SET receipt = ? WHERE n = 2", (json.dumps(dict(r2, prev="0" * 64)),), "n=2"),
        ("UPDATE receipts SET hash = ? WHERE n = 2", ("0" * 64,), "n=2"),
        ("UPDATE receipts SET store_sig = ? WHERE n = 3", (json.loads(original[0][1])["store_sig"],), "n=3"),
        ("DELETE FROM receipts WHERE n = 2", (), "n=2"),
        # a receipt taken out of the middle and the rest renumbered: every receipt still hashes and verifies, and
        # only the prev link shows the gap
        ("DELETE FROM receipts WHERE n = 2; UPDATE receipts SET n = 2 WHERE n = 3; UPDATE stores SET receipts = 2",
         (), "prev"),
        ("UPDATE stores SET receipts = 4", (), "4"),
    ]
    for sql, params, says in breaks:
        tamper(sql, *params)
        code, out = cli(capsys, "verify", "store-a", "--key", issuer, "--data-dir", str(data))
        assert code == 1 and says in out, (sql, out)
        tamper("DELETE FROM receipts WHERE store = 'store-a'")
        for n, text, h in original:
            tamper("INSERT INTO receipts (store, n, seq, receipt, hash, store_sig) VALUES (?, ?, ?, ?, ?, ?)",
                   "store-a", n, json.loads(text)["seq"], text, h, json.loads(text)["store_sig"])
        tamper("UPDATE stores SET receipts = 3")
        assert cli(capsys, "verify", "store-a", "--key", issuer, "--data-dir", str(data))[0] == 0


# ── deploy/notary_register.sh against a stub root ───────────────────────────────────────────────────
STUBS = {
    "systemctl": r'''
echo "systemctl $*" >> "$STATE/log"
case "$1" in
  is-active) [ ! -e "$STATE/inactive" ] ;;
  show)
    case "$*" in
      *" -p User "*) cat "$STATE/user" ;;
      *" -p WorkingDirectory "*) cat "$STATE/workdir" ;;
      *" -p Environment "*) cat "$STATE/environment" ;;
      *" -p ExecStart "*) cat "$STATE/execstart" ;;
      *" -p EnvironmentFiles "*) [ ! -e "$STATE/envfiles" ] || cat "$STATE/envfiles" ;;
      *) exit 1 ;;
    esac ;;
  *) exit 1 ;;
esac
''',
    "sudo": r'''
echo "sudo $*" >> "$STATE/log"
if [ "$1" = "-u" ]; then echo "$2" >> "$STATE/ran_as"; shift 2; fi
exec "$@"
''',
}


def bash() -> str:
    """Git's bash on Windows, never the WSL launcher in system32."""
    candidates = [r"C:\Program Files\Git\bin\bash.exe"] if os.name == "nt" else []
    found = [c for c in (*candidates, shutil.which("bash")) if c and os.path.exists(c)]
    assert found, "this test needs bash"
    return found[0]


class Box:
    """A stub root: a unit that names a user, a working directory, the code, the data directory and the interpreter."""

    def __init__(self, tmp: Path):
        self.root, self.state, self.bin = tmp / "root", tmp / "state", tmp / "bin"
        self.data = self.root / "data"
        for d in (self.data, self.state, self.bin):
            d.mkdir(parents=True)
        for name, body in STUBS.items():
            p = self.bin / name
            p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
            p.chmod(0o755)
        py = Path(sys.executable).as_posix()
        self.put("user", "svc-notary")
        self.put("workdir", self.root.as_posix())
        self.put("environment", f"PYTHONPATH={SRC.as_posix()} CONCORDANCE_DATA_DIR={self.data.as_posix()} "
                                f"CONCORDANCE_PUBLIC_BASE=https://example.org")
        self.put("execstart", f"{{ path={py} ; argv[]={py} -m concordance serve --host 127.0.0.1 --port 8020 ; "
                              f"ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; "
                              f"status=0/0 }}")
        self.script = tmp / "notary_register.sh"           # a Windows checkout is CRLF, which bash cannot read
        self.script.write_text(SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n"), encoding="utf-8", newline="\n")

    def put(self, name: str, text: str) -> None:
        (self.state / name).write_text(text + "\n", encoding="utf-8", newline="\n")

    def run(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items()          # only what the unit gives reaches the CLI
               if k not in ("CONCORDANCE_DATA_DIR", "PYTHONPATH", "CONCORDANCE_ISSUER_KEY", "CONCORDANCE_PUBLISH")}
        env["STATE"] = self.state.as_posix()
        first = ('stubs="$1"; shift; if command -v cygpath >/dev/null; then stubs="$(cygpath -u "$stubs")"; fi; '
                 'PATH="$stubs:$PATH" exec bash "$@"')
        return subprocess.run([bash(), "-c", first, "stubs", self.bin.as_posix(), self.script.as_posix(), *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)

    @property
    def log(self) -> str:
        p = self.state / "log"
        return p.read_text(encoding="utf-8") if p.exists() else ""


def test_the_script_registers_and_retires_as_the_units_user_with_its_interpreter_code_and_data(tmp_path):
    box = Box(tmp_path)
    s = Store("store-a")
    done = box.run("register", "store-a", s.public)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (box.state / "ran_as").read_text(encoding="utf-8").split() == ["svc-notary", "svc-notary"]   # the command, the read-back
    assert box.log.index("systemctl is-active") < box.log.index("sudo ")
    assert "registered store-a" in done.stdout
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("store-a")]
    assert len(lines) == 1 and "registered" in lines[0]                # read back with notary list
    assert sorted(tree(box.data)) == ["notary", "notary/notary.db"]
    done = box.run("retire", "store-a")
    assert done.returncode == 0, done.stdout + done.stderr
    assert [ln for ln in done.stdout.splitlines() if ln.startswith("store-a")][0].split()[1] == "retired"


def test_the_script_refuses_when_the_service_is_not_active_or_the_command_is_unknown(tmp_path):
    box = Box(tmp_path)
    s = Store("store-a")
    box.put("inactive", "")
    done = box.run("register", "store-a", s.public)
    assert done.returncode == 3 and "not active" in done.stdout and "nothing was changed" in done.stdout
    assert "sudo" not in box.log and tree(box.data) == {}
    (box.state / "inactive").unlink()
    for args in (("drop", "store-a"), ()):
        done = box.run(*args)
        assert done.returncode == 3 and "nothing was changed" in done.stdout, done.stdout
    assert "sudo" not in box.log and tree(box.data) == {}
    box.put("user", "")
    done = box.run("register", "store-a", s.public)
    assert done.returncode == 3 and "user" in done.stdout and "sudo" not in box.log and tree(box.data) == {}
    box.put("user", "root")                                            # a unit that runs as root is refused too
    done = box.run("register", "store-a", s.public)
    assert done.returncode == 3 and "runs as root" in done.stdout and "nothing was changed" in done.stdout
    assert "sudo" not in box.log and tree(box.data) == {}


def issuer_seed() -> tuple:
    key = Ed25519PrivateKey.generate()
    seed = b64u(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                  serialization.NoEncryption()))
    return seed, b64u(raw_public(key))


def test_the_script_passes_the_units_environment_file_so_verify_finds_the_key_and_never_prints_it(tmp_path,
                                                                                                   monkeypatch):
    box = Box(tmp_path)
    seed, _public = issuer_seed()                                     # generated here, never a real key
    unit_env = box.root / "unit.env"
    unit_env.write_text(f"# the unit's environment file\nCONCORDANCE_ISSUER_KEY={seed}\nCONCORDANCE_PUBLISH=1\n",
                        encoding="utf-8", newline="\n")
    s = Store("store-a")
    box.put("envfiles", f"{(box.root / 'missing.env').as_posix()} (ignore_errors=yes)")
    assert box.run("register", "store-a", s.public).returncode == 0
    monkeypatch.setenv("CONCORDANCE_DATA_DIR", str(box.data))
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", seed)
    monkeypatch.setattr(notary, "clock", Clock())
    assert notary.post(s.body(1))[0] == 200
    done = box.run("verify", "store-a")                               # a missing file the unit ignores is skipped
    assert done.returncode == 2 and "no key" in done.stdout, done.stdout + done.stderr
    box.put("envfiles", f"{(box.root / 'missing.env').as_posix()} (ignore_errors=yes) "
                        f"{unit_env.as_posix()} (ignore_errors=yes)")
    done = box.run("verify", "store-a")
    assert done.returncode == 0 and "store-a: 1 receipts" in done.stdout, done.stdout + done.stderr
    assert f"--env-file {unit_env.as_posix()}" in box.log                # the file is passed by its path
    assert seed not in done.stdout + done.stderr + box.log            # the key is never an argument or printed


def test_env_file_loads_the_units_variables_and_refuses_another_data_dir(data, issuer, clock, capsys, monkeypatch,
                                                                         tmp_path):
    s = Store("store-a")
    cli(capsys, "register", "store-a", s.public, "--data-dir", str(data))
    assert notary.post(s.body(1))[0] == 200
    seed = os.environ["CONCORDANCE_ISSUER_KEY"]
    monkeypatch.setenv("CONCORDANCE_ISSUER_KEY", "")                  # only the file gives the key now
    monkeypatch.setenv("CONCORDANCE_PUBLISH", "")
    unit_env = tmp_path / "unit.env"
    unit_env.write_text(f"\n# a comment\n; another\nCONCORDANCE_ISSUER_KEY=\"{seed}\"\n CONCORDANCE_PUBLISH = '1' \n",
                        encoding="utf-8")
    code, out = cli(capsys, "verify", "store-a", "--env-file", str(unit_env), "--data-dir", str(data))
    assert code == 0 and "1 receipts" in out and seed not in out, out
    assert os.environ["CONCORDANCE_PUBLISH"] == "1"
    elsewhere = tmp_path / "elsewhere.env"
    elsewhere.write_text(f"CONCORDANCE_DATA_DIR={tmp_path / 'other'}\n", encoding="utf-8")
    code, out = cli(capsys, "list", "--env-file", str(elsewhere), "--data-dir", str(data))
    assert code == 2 and "another directory" in out
    broken = tmp_path / "broken.env"
    broken.write_text(f"{seed}\n", encoding="utf-8")                  # not NAME=VALUE: named by line, never shown
    code, out = cli(capsys, "list", "--env-file", str(broken), "--data-dir", str(data))
    assert code == 2 and "broken.env:1" in out and seed not in out
    code, out = cli(capsys, "list", "--env-file", str(tmp_path / "absent.env"), "--data-dir", str(data))
    assert code == 2


def test_a_command_the_cli_refuses_changes_nothing_and_the_script_says_so(tmp_path):
    box = Box(tmp_path)
    done = box.run("register", "store-a", "not-a-key")
    assert done.returncode == 1, done.stdout + done.stderr
    assert tree(box.data) == {}
    assert "no store" in done.stdout                                   # the read-back still ran, and read only
