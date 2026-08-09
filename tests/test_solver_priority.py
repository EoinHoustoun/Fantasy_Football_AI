"""Background solves must yield to the one a human is waiting on.

The draft page kicks off eight ceiling MILPs in a daemon thread at load, each
with a 25-second limit. On an 8-core machine that saturates the box, and the
foreground solve a human is actually waiting for went from 4 seconds to 41.

`solver_gate` is a priority gate, not a plain lock: foreground work never
queues behind background work, and background work steps aside while any
foreground solve is in flight.
"""
import threading
import time

from analytics import solver_gate


def setup_function():
    solver_gate.reset()


def test_background_runs_when_nothing_is_in_the_foreground():
    with solver_gate.background():
        assert True


def test_background_waits_while_a_foreground_solve_is_running():
    order = []
    started = threading.Event()

    def _bg():
        started.set()
        with solver_gate.background():
            order.append("bg")

    with solver_gate.foreground():
        t = threading.Thread(target=_bg, daemon=True)
        t.start()
        started.wait(1)
        time.sleep(0.15)          # background must still be waiting here
        order.append("fg")
    t.join(2)
    assert order == ["fg", "bg"], order


def test_foreground_never_waits_for_background():
    """The point of the gate · a human must not queue behind a warm-up."""
    holding = threading.Event()
    release = threading.Event()

    def _bg():
        with solver_gate.background():
            holding.set()
            release.wait(2)

    threading.Thread(target=_bg, daemon=True).start()
    holding.wait(1)
    t0 = time.perf_counter()
    with solver_gate.foreground():
        waited = time.perf_counter() - t0
    release.set()
    assert waited < 0.1, "foreground queued behind a background solve (%.2fs)" % waited


def test_nested_foreground_is_safe():
    with solver_gate.foreground():
        with solver_gate.foreground():
            pass
    # the gate must be clear again, or every later background solve stalls
    with solver_gate.background():
        assert True


def test_an_exception_in_the_foreground_still_clears_the_gate():
    try:
        with solver_gate.foreground():
            raise RuntimeError("solver blew up")
    except RuntimeError:
        pass
    with solver_gate.background():
        assert True
