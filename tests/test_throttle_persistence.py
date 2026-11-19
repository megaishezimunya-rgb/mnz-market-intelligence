"""Failed-attempt counters are stored, so a restart does not reset the backoff."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BASE = 1_700_000_000.0


def _clock(start: float = BASE):
    """A wall-clock-like fake so stored timestamps stay realistic."""
    state = {"now": start}
    return state, lambda: state["now"]


def test_attempts_survive_a_new_throttle_instance(db):
    from auth import AttemptThrottle

    _, clock = _clock()
    first = AttemptThrottle(clock=clock, store=db)
    for _ in range(6):
        first.record_failure("Persist@Example.com ")

    # A fresh process (redeploy) reads the same counter from the database.
    second = AttemptThrottle(clock=clock, store=db)
    assert second.retry_after("persist@example.com") == 30
    row = db.get_login_attempt("persist@example.com")
    assert row is not None and row["failures"] == 6


def test_counter_is_shared_between_workers(db):
    from auth import AttemptThrottle

    _, clock = _clock()
    first = AttemptThrottle(clock=clock, store=db)
    second = AttemptThrottle(clock=clock, store=db)
    for _ in range(6):
        first.record_failure("shared@example.com")

    # The other worker sees the pause and extends it on its next failure.
    assert second.retry_after("shared@example.com") == 30
    assert second.record_failure("shared@example.com") == 60
    assert first.retry_after("shared@example.com") == 60


def test_successful_login_clears_the_stored_counter(db):
    from auth import AttemptThrottle

    _, clock = _clock()
    throttle = AttemptThrottle(clock=clock, store=db)
    for _ in range(6):
        throttle.record_failure("cleared@example.com")
    assert db.get_login_attempt("cleared@example.com") is not None

    throttle.clear("cleared@example.com")
    assert db.get_login_attempt("cleared@example.com") is None
    assert AttemptThrottle(clock=clock, store=db).retry_after("cleared@example.com") == 0


def test_quiet_period_resets_the_stored_count(db):
    from auth import AttemptThrottle

    state, clock = _clock()
    throttle = AttemptThrottle(clock=clock, store=db)
    for _ in range(6):
        throttle.record_failure("quiet@example.com")
    assert throttle.retry_after("quiet@example.com") == 30

    state["now"] += throttle.decay + 60
    assert throttle.retry_after("quiet@example.com") == 0
    assert throttle.record_failure("quiet@example.com") == 0


def test_old_rows_are_pruned_on_write(db):
    db.save_login_attempt("stale@example.com", failures=9,
                          last_failure=BASE - 30 * 24 * 60 * 60)
    db.save_login_attempt("fresh@example.com", failures=1, last_failure=BASE)

    assert db.get_login_attempt("stale@example.com") is None
    assert db.get_login_attempt("fresh@example.com") is not None


def test_unreachable_storage_falls_back_to_memory():
    from auth import AttemptThrottle

    class Broken:
        def get_login_attempt(self, key):  # pragma: no cover - exercised via call
            raise RuntimeError("database is down")

        def save_login_attempt(self, *args, **kwargs):
            raise RuntimeError("database is down")

    _, clock = _clock()
    throttle = AttemptThrottle(clock=clock, store=Broken())
    for _ in range(6):
        throttle.record_failure("offline@example.com")

    assert throttle.retry_after("offline@example.com") == 30
