"""Progress for the TeddyClip window's progress bar.

Work is split into nested bands: the whole job is 0..1, each recording takes
its share of that, and each stage of a recording (transcribing, cutting...)
takes its share of the recording. Code inside a stage only reports how far
through that stage it is; `band` maps it to the whole job. With no listener
(the command line), reporting does nothing."""

from __future__ import annotations

import contextlib
import threading

_lock = threading.Lock()
_listener = None
_lo, _hi, _label = 0.0, 1.0, ""


def listen(fn) -> None:
    """`fn(label, fraction)` is called with the overall fraction of the job, 0..1.
    Pass None to stop listening."""
    global _listener, _lo, _hi, _label
    with _lock:
        _listener, _lo, _hi, _label = fn, 0.0, 1.0, ""


@contextlib.contextmanager
def band(start: float, end: float, label: str | None = None):
    """Run a stage that covers `start`..`end` of the current band."""
    global _lo, _hi, _label
    with _lock:
        saved = (_lo, _hi, _label)
        width = _hi - _lo
        _lo, _hi = _lo + width * start, _lo + width * end
        if label is not None:
            _label = label
    step(0.0)
    try:
        yield
    finally:
        step(1.0)
        with _lock:
            _lo, _hi, _label = saved


def step(fraction: float, label: str | None = None) -> None:
    """Report how far through the current band the work is (0..1)."""
    with _lock:
        fn = _listener
        if fn is None:
            return
        text = label or _label
        overall = _lo + (_hi - _lo) * min(1.0, max(0.0, fraction))
    fn(text, overall)
