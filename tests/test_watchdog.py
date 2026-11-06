"""A second, independent way to stay alive: a frozen process stops notifying, and systemd restarts it, whatever froze it.

The serve process tells systemd WATCHDOG=1 only after its own read of /health answers, by the plain NOTIFY_SOCKET
protocol. Nothing is needed from the code that froze, which is the point: a process that cannot answer sends nothing.
That systemd then restarts it is proved once on the box, not here: these tests stop at the datagram.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "fixtures" / "cell_probe.py"
UNIT = ROOT / "deploy" / "nh-v3.service"
sys.path.insert(0, str(ROOT / "src"))

from concordance import http_api  # noqa: E402


def setting(name: str) -> str:
    """One line of the unit, whatever the checkout's line endings."""
    return re.search(rf"^{name}=(.*?)\s*$", UNIT.read_text(encoding="utf-8"), re.M).group(1)


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
    threading.Thread(target=srv.serve_forever, args=(0.01,), daemon=True).start()
    yield srv.server_address
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def sent(monkeypatch):
    """What would have gone to systemd."""
    out = []
    monkeypatch.setattr(http_api, "_notify", lambda message: out.append(message) or True)
    return out


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()


# ── a beat ───────────────────────────────────────────────────────────────────────────────────────────
def test_an_answered_self_read_sends_one_notify(server, sent):
    assert http_api._beat(server) is True
    assert sent == [b"WATCHDOG=1"]


def test_a_failed_self_read_sends_no_notify(sent):
    assert http_api._beat(closed_port()) is False
    assert sent == []


def test_a_wrong_answer_is_a_failed_self_read(sent, monkeypatch):
    """Anything but /health's own answer sends nothing: a server that answers something else is not this engine."""
    def not_ok(*_a):
        return 200, {}, b'{"ok": false}'

    monkeypatch.setattr(http_api, "route", not_ok)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), http_api.Handler)
    threading.Thread(target=srv.serve_forever, args=(0.01,), daemon=True).start()
    try:
        assert http_api._beat(srv.server_address) is False
    finally:
        srv.shutdown()
        srv.server_close()
    assert sent == []


def test_the_self_read_has_its_own_short_timeout(sent):
    """A port that takes the connection and never answers: the read gives up by itself, and nothing is sent."""
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        began = time.monotonic()
        assert http_api._self_read(silent.getsockname(), timeout=0.1) is False
        assert time.monotonic() - began < 5
    assert sent == []


# ── the protocol ─────────────────────────────────────────────────────────────────────────────────────
class Socket:
    """A stand-in for a datagram socket, for a platform with no AF_UNIX and for a socket that fails."""
    made = []

    def __init__(self, family, kind):
        Socket.made.append((family, kind))
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def sendto(self, message, target):
        Socket.sent.append((message, target))


class Sockets:
    AF_UNIX, SOCK_DGRAM, socket = "unix", "dgram", Socket


def test_notify_sends_one_datagram_to_the_named_socket(monkeypatch):
    Socket.made, Socket.sent = [], []
    monkeypatch.setattr(http_api, "socket", Sockets)
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    assert http_api._notify(b"WATCHDOG=1") is True
    monkeypatch.setenv("NOTIFY_SOCKET", "@abstract")
    assert http_api._notify(b"WATCHDOG=1") is True
    assert Socket.made == [("unix", "dgram")] * 2
    assert Socket.sent == [(b"WATCHDOG=1", "/run/systemd/notify"), (b"WATCHDOG=1", "\0abstract")]


def test_an_absent_notify_socket_does_nothing(monkeypatch):
    Socket.made, Socket.sent = [], []
    monkeypatch.setattr(http_api, "socket", Sockets)
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setenv("WATCHDOG_USEC", "30000000")
    assert http_api._notify(b"WATCHDOG=1") is False
    assert http_api._start_watchdog(("127.0.0.1", 1)) is None       # and no thread is started for it
    assert Socket.made == []


def test_no_watchdog_asked_for_starts_nothing(monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.delenv("WATCHDOG_USEC", raising=False)
    assert http_api._start_watchdog(("127.0.0.1", 1)) is None


def test_a_socket_that_fails_does_not_stop_the_watchdog(monkeypatch):
    class Refusing(Socket):
        def sendto(self, _message, _target):
            raise OSError("no such socket")

    class Refused:
        AF_UNIX, SOCK_DGRAM, socket = "unix", "dgram", Refusing

    monkeypatch.setattr(http_api, "socket", Refused)
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    assert http_api._notify(b"WATCHDOG=1") is False


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX on this platform: the stand-in above covers it")
def test_notify_reaches_a_real_datagram_socket(monkeypatch, tmp_path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind(str(tmp_path / "notify"))
        receiver.settimeout(5)
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "notify"))
        assert http_api._notify(b"WATCHDOG=1") is True
        assert receiver.recv(64) == b"WATCHDOG=1"


# ── the thread ───────────────────────────────────────────────────────────────────────────────────────
def test_the_watchdog_beats_at_a_quarter_of_what_systemd_asked_for(server, sent, monkeypatch):
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.setenv("WATCHDOG_USEC", "80000")
    thread = http_api._start_watchdog(server)
    assert thread is not None and thread.daemon
    end = time.monotonic() + 10
    while len(sent) < 3 and time.monotonic() < end:
        time.sleep(0.005)
    thread.stop.set()
    thread.join(5)
    assert len(sent) >= 3 and not thread.is_alive()
    assert http_api._beats_every(80000) == pytest.approx(0.02)


def test_serve_starts_the_watchdog(monkeypatch):
    started = []

    class Server:
        server_address = ("0.0.0.0", 8020)

        def __init__(self, *_a):
            pass

        def serve_forever(self):
            pass

    monkeypatch.setattr(http_api, "use_cells", lambda: None)
    monkeypatch.setattr(http_api, "ThreadingHTTPServer", Server)
    monkeypatch.setattr(http_api, "_start_watchdog", started.append)
    http_api.serve("0.0.0.0", 8020, background=True)
    assert started == [("127.0.0.1", 8020)]                         # it reads itself on loopback, whatever it binds


# ── the unit ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_unit_asks_for_the_watchdog():
    assert int(setting("WatchdogSec")) > 0
    assert setting("NotifyAccess") == "main"
    assert setting("Restart") == "on-failure"                       # a watchdog timeout is a failure


class Clock:
    """The watchdog's own time, so the real loop runs at the unit's real numbers in no time at all."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


def gaps_between_notifies(reads, monkeypatch):
    """Run the real _watchdog over `reads`, each (seconds it takes, whether it answers), at the unit's real timings, and
    return the gaps between the notifies that went out."""
    window_s = int(setting("WatchdogSec"))
    clock, reads, notes = Clock(), list(reads), []

    class Stop:
        def wait(self, seconds):
            clock.now += seconds
            return not reads

    def read(_address):
        seconds, answered = reads.pop(0)
        clock.now += seconds
        return answered

    monkeypatch.setattr(http_api, "time", clock)
    monkeypatch.setattr(http_api, "_self_read", read)
    monkeypatch.setattr(http_api, "_notify", lambda _message: notes.append(clock.now) or True)
    http_api._watchdog(("127.0.0.1", 1), http_api._beats_every(window_s * 10 ** 6), Stop())
    return window_s, [b - a for a, b in zip(notes, notes[1:])]


QUICK, SLOW, TIMED_OUT, REFUSED = (0.01, True), (http_api.SELF_READ_S, True), (http_api.SELF_READ_S, False), (0.01, False)


def test_two_failed_reads_survive_the_window_however_they_fail(monkeypatch):
    for failed in (TIMED_OUT, REFUSED):
        for last in (QUICK, SLOW):
            window_s, gaps = gaps_between_notifies([QUICK, failed, failed, last], monkeypatch)
            assert len(gaps) == 1 and gaps[0] < window_s, (failed, last, gaps)


def test_a_third_failed_read_does_not(monkeypatch):
    window_s, gaps = gaps_between_notifies([QUICK, REFUSED, REFUSED, REFUSED, QUICK], monkeypatch)
    assert gaps[0] >= window_s - 0.1


def test_slow_answers_are_answers_and_never_drift_past_the_beat(monkeypatch):
    window_s, gaps = gaps_between_notifies([SLOW] * 8, monkeypatch)
    assert len(gaps) == 7 and max(gaps) < window_s / 2
    assert http_api.SELF_READ_S < http_api._beats_every(window_s * 10 ** 6)     # a read ends before the next one starts


def test_the_memory_wall_stands_outside_the_cells():
    assert re.fullmatch(r"\d+[MG]", setting("MemoryMax"))
    assert setting("OOMPolicy") == "continue"                       # the kernel ends a cell, the unit keeps running


# ── a frozen process, with the stand-in ──────────────────────────────────────────────────────────────
def beats(mode, tmp_path, watch_s):
    """Run a probe mode that prints a line per notify, then kill it `watch_s` after its read began."""
    env = dict(os.environ, CONCORDANCE_DATA_DIR=str(tmp_path), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, str(PROBE), mode], stdout=subprocess.PIPE, text=True, env=env)
    lines, read_seen = [], threading.Event()

    def pump():
        for line in p.stdout:
            lines.append(line.split())
            if line.startswith("read"):
                read_seen.set()

    threading.Thread(target=pump, daemon=True).start()
    try:
        assert read_seen.wait(60), "the child never reached the read"
        time.sleep(watch_s)
    finally:
        p.kill()
        p.wait()
    read_at = next(float(ln[1]) for ln in lines if ln[0] == "read")
    notes = [float(ln[1]) for ln in lines if ln[0] == "notify"]
    return [t for t in notes if t <= read_at], [t for t in notes if t > read_at + 0.25]


@pytest.mark.slow
def test_a_real_loop_on_a_real_clock_has_the_same_gaps(monkeypatch):
    """The same schedule on real time, a hundred times faster, through real threads and a real Event."""
    window_s, scale = int(setting("WatchdogSec")), 100
    reads, notes = [QUICK, TIMED_OUT, TIMED_OUT, SLOW], []
    stop = threading.Event()

    def read(_address):
        seconds, answered = reads.pop(0)
        time.sleep(seconds / scale)
        if not reads:
            stop.set()
        return answered

    monkeypatch.setattr(http_api, "_self_read", read)
    monkeypatch.setattr(http_api, "_notify", lambda _message: notes.append(time.monotonic()) or True)
    http_api._watchdog(("127.0.0.1", 1), http_api._beats_every(window_s * 10 ** 6) / scale, stop)
    assert len(notes) == 2 and notes[1] - notes[0] < window_s / scale


@pytest.mark.slow
def test_a_busy_process_answers_inside_the_self_read(server, capsys):
    """Not a frozen process: 32 threads spinning in Python, as many as this was measured at."""
    stop, seen = threading.Event(), []

    def spin():
        n = 0
        while not stop.is_set():
            n = (n * 31 + 7) % 1000003

    spinners = [threading.Thread(target=spin, daemon=True) for _ in range(32)]
    for t in spinners:
        t.start()
    try:
        for _ in range(3):
            began = time.monotonic()
            assert http_api._self_read(server) is True
            seen.append(round(time.monotonic() - began, 2))
    finally:
        stop.set()
        for t in spinners:
            t.join()
    with capsys.disabled():
        print("\nSELF READ WITH 32 BUSY THREADS", seen)


@pytest.mark.slow
def test_a_frozen_process_stops_notifying_and_a_stuck_cell_does_not(tmp_path):
    before, after = beats("freeze", tmp_path, 1.5)
    assert len(before) >= 3                                         # it was notifying
    assert not after                                                # the lock held it: nothing went out

    before, after = beats("stuck", tmp_path, 1.5)
    assert len(before) >= 3 and len(after) >= 3                     # a stuck cell is not a frozen process

