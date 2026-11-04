import json
import os
import time

import pytest

from teddyclip import cli, ui


@pytest.fixture
def job(monkeypatch):
    started = []
    j = ui.Job()
    monkeypatch.setattr(j, "start", lambda name, work: started.append(name) or True)
    j.started_names = started
    return j


def recording(path, age=600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    old = time.time() - age
    os.utime(path, (old, old))
    return path


def test_off_by_default_does_nothing(cfg, job):
    recording(cfg.paths.inbox / "session.mp4")
    assert ui.load_settings(cfg) == {"auto": False, "auto_game": ""}
    assert ui.auto_tick(cfg, job) == "off" and job.started_names == []


def test_on_files_loose_recordings_under_the_game_and_starts(cfg, job):
    ui.save_settings(cfg, {"auto": True, "auto_game": "Elden Ring"})
    rec = recording(cfg.paths.inbox / "2026-11-05 20-00-00.mp4")
    assert ui.auto_tick(cfg, job) == "started"
    assert job.started_names == ["Finding clips (automatic)"]
    assert (cfg.paths.inbox / "Elden Ring" / rec.name).exists() and not rec.exists()


def test_waits_while_obs_is_still_writing(cfg, job, monkeypatch):
    ui.save_settings(cfg, {"auto": True, "auto_game": ""})
    recording(cfg.paths.inbox / "done.mp4")
    growing = recording(cfg.paths.inbox / "live.mkv", age=0)  # just written to
    assert ui.auto_tick(cfg, job) == "recording" and job.started_names == []
    assert "Waiting for OBS" in ui.auto_status(cfg, job, ui.load_settings(cfg))
    old = time.time() - 600
    os.utime(growing, (old, old))
    assert ui.auto_tick(cfg, job) == "started"


def test_no_game_leaves_recordings_where_they_are(cfg, job):
    ui.save_settings(cfg, {"auto": True, "auto_game": ""})
    rec = recording(cfg.paths.inbox / "session.mp4")
    assert ui.auto_tick(cfg, job) == "started" and rec.exists()


def test_nothing_to_do_and_busy(cfg, job, monkeypatch):
    ui.save_settings(cfg, {"auto": True, "auto_game": ""})
    assert ui.auto_tick(cfg, job) == "nothing"
    recording(cfg.paths.inbox / "session.mp4")
    job.running = True
    assert ui.auto_tick(cfg, job) == "busy" and job.started_names == []


def test_settings_survive_a_broken_file(cfg):
    path = cfg.paths.cache / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert ui.load_settings(cfg) == ui.DEFAULT_SETTINGS
    path.write_text(json.dumps({"auto": "yes", "auto_game": "../.."}), encoding="utf-8")
    assert ui.load_settings(cfg) == {"auto": False, "auto_game": ""}


def test_settings_endpoint_saves_and_shows_status(cfg):
    import threading
    import urllib.request

    srv = ui.make_server(cfg, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        req = urllib.request.Request(base + "/api/settings", method="POST",
                                     data=json.dumps({"auto": True, "auto_game": "GTA: V"}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read()) == {"auto": True, "auto_game": "GTA V"}
        with urllib.request.urlopen(base + "/api/state") as r:
            st = json.loads(r.read())
        assert st["settings"]["auto"] and "Watching 1 - Raw recordings" in st["auto_status"]
    finally:
        srv.shutdown()
        srv.server_close()
