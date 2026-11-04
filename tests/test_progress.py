import time

import pytest

from teddyclip import progress, ui


@pytest.fixture
def heard():
    seen = []
    progress.listen(lambda label, fraction: seen.append((label, round(fraction, 3))))
    yield seen
    progress.listen(None)


def test_nested_bands_map_to_the_whole_job(heard):
    with progress.band(0.5, 1.0):  # second of two recordings
        with progress.band(0.0, 0.5, "Transcribing"):
            progress.step(0.5)
    assert ("Transcribing", 0.625) in heard
    assert heard[-1] == ("", 1.0)  # leaving the recording's band reports it complete


def test_step_label_overrides_and_values_are_clamped(heard):
    with progress.band(0.0, 1.0, "Cutting clips"):
        progress.step(0.5, "Cutting clip 2 of 4")
        progress.step(7)
    assert ("Cutting clip 2 of 4", 0.5) in heard and ("Cutting clips", 1.0) in heard


def test_reporting_without_a_listener_does_nothing():
    progress.listen(None)
    with progress.band(0.0, 0.5, "Transcribing"):
        progress.step(0.3)  # no error, nothing to call


def test_job_shows_step_fraction_and_finishes_at_100_percent():
    job = ui.Job()

    def work():
        with progress.band(0.0, 0.6, "Transcribing what you said"):
            progress.step(0.5)
            time.sleep(0.05)
            seen.append(job.state())
        return 0

    seen = []
    assert job.start("Making clips", work)
    for _ in range(100):
        if not job.state()["running"]:
            break
        time.sleep(0.02)
    during, after = seen[0], job.state()
    assert during["step"] == "Transcribing what you said" and during["fraction"] == pytest.approx(0.3)
    assert after["fraction"] == 1.0 and not after["running"] and after["elapsed"] > 0


def test_progress_never_goes_backwards():
    job = ui.Job()
    job._progress("Transcribing", 0.4)
    job._progress("Measuring loudness", 0.2)
    assert job.state()["fraction"] == 0.4 and job.state()["step"] == "Measuring loudness"


def test_job_keeps_the_pc_awake_only_while_it_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(ui, "stay_awake", lambda on: calls.append(on))
    job = ui.Job()
    job.start("Making clips", lambda: calls.append("working") or 0)
    for _ in range(100):
        if not job.state()["running"]:
            break
        time.sleep(0.02)
    assert calls == [True, "working", False]


def test_job_lets_the_pc_sleep_again_after_a_crash(monkeypatch):
    calls = []
    monkeypatch.setattr(ui, "stay_awake", lambda on: calls.append(on))

    def boom():
        raise RuntimeError("bug")

    job = ui.Job()
    job.start("Making clips", boom)
    for _ in range(100):
        if not job.state()["running"]:
            break
        time.sleep(0.02)
    assert calls == [True, False] and job.state()["failed"]
