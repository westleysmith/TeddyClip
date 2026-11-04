import json
import os
import threading
import time
import urllib.error
import urllib.request

import pytest

from teddyclip import cli, ui


@pytest.fixture
def server(cfg):
    srv = ui.make_server(cfg, port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def session(cfg):
    folder = cfg.paths.clips / "2026-11-03 Elden Ring"
    folder.mkdir(parents=True)
    (folder / "0h00m09s - Clip that - Boss fight.mp4").write_bytes(b"0123456789")
    (folder / "moments.csv").write_text(
        "keep,start,end,score,kind,title,why,events,file\n"
        "yes,0:00:10,0:00:55,10.0,trigger,Boss fight,trigger,YOU DIED,0h00m09s - Clip that - Boss fight.mp4\n",
        encoding="utf-8-sig")
    return folder


def get(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {})) as r:
        return r.status, dict(r.headers), r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_page_is_served(server):
    status, headers, body = get(server + "/")
    assert status == 200 and b"TeddyClip" in body and headers["Content-Type"].startswith("text/html")


def test_state_lists_inbox_and_clips_with_csv_notes(server, cfg, session):
    (cfg.paths.inbox / "new.mp4").write_bytes(b"x")
    st = json.loads(get(server + "/api/state")[2])
    assert [f["name"] for f in st["inbox"]] == ["new.mp4"]
    clip = st["sessions"][0]["clips"][0]
    assert st["sessions"][0]["name"] == "2026-11-03 Elden Ring"
    assert (clip["title"], clip["kind"], clip["start"], clip["length"]) == ("Boss fight", "trigger", "0:00:10", 45)
    assert clip["events"] == ["YOU DIED"]
    assert st["sessions"][0]["highlight"] is None and st["job"]["running"] is False


def test_media_supports_ranges_for_seeking(server, session):
    status, headers, body = get(server + "/api/state")
    url = json.loads(body)["sessions"][0]["clips"][0]["url"]
    status, headers, body = get(server + url, {"Range": "bytes=2-5"})
    assert status == 206 and body == b"2345" and headers["Content-Range"] == "bytes 2-5/10"
    status, headers, body = get(server + url)
    assert status == 200 and body == b"0123456789" and headers["Accept-Ranges"] == "bytes"


@pytest.mark.parametrize("path", ["/media/clips/../config.yaml", "/media/clips/%2E%2E/x/y",
                                  "/media/clips/a/..%5Cb.mp4", "/media/other/x.mp4"])
def test_media_never_leaves_the_teddyclip_folders(server, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + path)
    assert e.value.code == 404


def test_delete_sends_the_clip_to_the_recycle_bin(server, session, monkeypatch):
    binned = []
    monkeypatch.setattr(ui, "to_recycle_bin", lambda p: (binned.append(p.name), p.unlink()))
    status, _ = post(server + "/api/delete", {"session": session.name, "file": "0h00m09s - Clip that - Boss fight.mp4"})
    assert status == 200 and binned == ["0h00m09s - Clip that - Boss fight.mp4"]
    assert not list(session.glob("*.mp4"))


@pytest.mark.parametrize("body", [{"session": "..", "file": "x.mp4"}, {"session": "a/b", "file": "x.mp4"},
                                  {"session": "s", "file": "moments.csv"}, {}])
def test_delete_rejects_anything_but_a_clip_name(server, body):
    assert post(server + "/api/delete", body)[0] == 400


def test_make_clips_runs_in_the_background_and_shows_its_output(server, monkeypatch):
    def fake(cfg, only=None):
        print("Transcribing...")
        print("Done: 1 processed, 0 failed")
        return 0
    monkeypatch.setattr(cli, "process_inbox", fake)
    assert post(server + "/api/process", {})[0] == 200
    for _ in range(50):
        job = json.loads(get(server + "/api/state")[2])["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["lines"] == ["Transcribing...", "Done: 1 processed, 0 failed"] and not job["failed"]


def test_only_one_job_at_a_time(server, session, monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(cli, "process_inbox", lambda cfg, only=None: gate.wait(5) and 0)
    assert post(server + "/api/process", {})[0] == 200
    assert post(server + "/api/highlight", {"session": session.name})[0] == 409
    gate.set()


def test_job_log_handles_carriage_return_progress():
    job = ui.Job()
    job.write("Transcribed up to 1.0s\rTranscribed up to 2.0s")
    job.write("\nMeasuring loudness...\n")
    assert job.state()["lines"] == ["Transcribed up to 1.0s", "Transcribed up to 2.0s", "Measuring loudness..."]


def test_titles_come_from_the_working_folder_notes(server, cfg):
    folder = cfg.paths.clips / "2026-11-04 Dark Souls"
    folder.mkdir(parents=True)
    (folder / "0h01m00s - Big jump.mp4").write_bytes(b"x")
    notes = cfg.paths.notes / folder.name
    notes.mkdir(parents=True)
    (notes / "moments.csv").write_text("keep,start,end,score,kind,title,why,events,file\n"
                                       "yes,0:01:00,0:01:40,8,laughter,Big jump,big laugh,,0h01m00s - Big jump.mp4\n",
                                       encoding="utf-8-sig")
    clip = json.loads(get(server + "/api/state")[2])["sessions"][0]["clips"][0]
    assert (clip["kind"], clip["why"]) == ("laughter", "big laugh")


def test_add_moves_recordings_into_the_game_folder(server, cfg, tmp_path):
    videos = tmp_path / "Videos"
    videos.mkdir()
    a, b = videos / "2026-11-04 20-00-00.mp4", videos / "2026-11-04 22-00-00.mkv"
    a.write_bytes(b"a" * 1000)
    b.write_bytes(b"b")
    (cfg.paths.inbox / "Elden Ring").mkdir(parents=True)
    (cfg.paths.inbox / "Elden Ring" / a.name).write_bytes(b"older")  # same name already there
    status, _ = post(server + "/api/add", {"files": [str(a), str(b)], "game": "Elden Ring"})
    assert status == 200
    for _ in range(100):
        if not json.loads(get(server + "/api/state")[2])["job"]["running"]:
            break
        time.sleep(0.05)
    inbox = cfg.paths.inbox / "Elden Ring"
    assert sorted(p.name for p in inbox.iterdir()) == sorted([a.name, f"{a.stem} (2).mp4", b.name])
    assert (inbox / f"{a.stem} (2).mp4").read_bytes() == b"a" * 1000
    assert not a.exists() and not b.exists()  # moved, not copied


def test_add_keeps_the_date_when_copying_across_drives(cfg, tmp_path, monkeypatch):
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"z" * 5000)
    old = time.time() - 3600
    os.utime(src, (old, old))
    real_replace = os.replace
    calls = []

    def cross_drive_once(a, b):  # the first rename fails as it would across drives
        calls.append(a)
        if len(calls) == 1:
            raise OSError("different drive")
        return real_replace(a, b)

    monkeypatch.setattr(ui.os, "replace", cross_drive_once)
    assert ui.add_recordings([src], "GTA", cfg) == 0
    moved = cfg.paths.inbox / "GTA" / "rec.mp4"
    assert moved.read_bytes() == b"z" * 5000 and not src.exists()
    assert abs(moved.stat().st_mtime - old) < 2  # still counts as a finished recording


@pytest.mark.parametrize("body", [{"files": []}, {"files": "C:/x.mp4"}, {"files": ["relative.mp4"]},
                                  {"files": ["C:/does/not/exist.mp4"]}])
def test_add_rejects_bad_requests(server, body):
    assert post(server + "/api/add", body)[0] == 400


def test_add_rejects_non_recordings(server, tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("x")
    status, body = post(server + "/api/add", {"files": [str(doc)]})
    assert status == 400 and "mp4" in body["error"]


@pytest.mark.parametrize("raw,clean", [("Elden Ring", "Elden Ring"), ("  GTA: V?  ", "GTA V"),
                                       ("../..", None), ("", None), (None, None)])
def test_game_names_are_safe_folder_names(raw, clean):
    assert ui.game_name(raw) == clean


def test_other_web_pages_cannot_act(server):
    req = urllib.request.Request(server + "/api/process", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403


def test_archive_puts_a_session_away_and_restore_brings_it_back(server, cfg, session):
    assert post(server + "/api/archive", {"session": session.name})[0] == 200
    st = json.loads(get(server + "/api/state")[2])
    assert st["sessions"] == [] and st["archived"] == [{"name": session.name, "clips": 1}]
    assert (cfg.paths.clips / "Archived" / session.name / "0h00m09s - Clip that - Boss fight.mp4").exists()
    assert post(server + "/api/unarchive", {"session": session.name})[0] == 200
    st = json.loads(get(server + "/api/state")[2])
    assert [s["name"] for s in st["sessions"]] == [session.name] and st["archived"] == []


def test_restoring_next_to_a_newer_session_of_the_same_name_keeps_both(server, cfg, session):
    post(server + "/api/archive", {"session": session.name})
    (cfg.paths.clips / session.name).mkdir()  # a newer session got the same name meanwhile
    assert post(server + "/api/unarchive", {"session": session.name})[0] == 200
    names = sorted(s["name"] for s in json.loads(get(server + "/api/state")[2])["sessions"])
    assert names == [session.name, f"{session.name} (2)"]


@pytest.mark.parametrize("body", [{"session": "Archived"}, {"session": ".."}, {"session": "missing"}, {}])
def test_archive_rejects_bad_names(server, body):
    assert post(server + "/api/archive", body)[0] in (400, 404)


def test_make_clips_for_just_the_ticked_recordings(server, cfg, monkeypatch):
    for rel in ("Lego Star Wars/a.mp4", "Worms/b.mp4"):
        f = cfg.paths.inbox / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    seen = {}
    monkeypatch.setattr(cli, "process_inbox", lambda c, only=None: seen.update(only=only) or 0)
    # The page lists names with Windows backslashes.
    assert post(server + "/api/process", {"files": [r"Lego Star Wars\a.mp4"]})[0] == 200
    for _ in range(100):
        if "only" in seen:
            break
        time.sleep(0.02)
    assert [s.replace("\\", "/") for s in seen["only"]] == ["Lego Star Wars/a.mp4"]


@pytest.mark.parametrize("files", [[], [r"..\..\Windows\win.ini"], ["../../x.mp4"], ["missing.mp4"], [5], "a.mp4"])
def test_make_clips_rejects_anything_outside_raw_recordings(server, files):
    assert post(server + "/api/process", {"files": files})[0] == 400


def test_a_remade_clip_gets_a_new_link_so_the_player_reloads_it(server, session):
    clip = session / "0h00m09s - Clip that - Boss fight.mp4"
    first = json.loads(get(server + "/api/state")[2])["sessions"][0]["clips"][0]["url"]
    clip.write_bytes(b"a longer, finished clip")
    second = json.loads(get(server + "/api/state")[2])["sessions"][0]["clips"][0]["url"]
    assert first != second and first.split("?")[0] == second.split("?")[0]
    assert get(server + second)[2] == b"a longer, finished clip"


def test_raw_recordings_can_be_previewed(server, cfg):
    f = cfg.paths.inbox / "Lego Star Wars" / "session.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"0123456789")
    rec = json.loads(get(server + "/api/state")[2])["inbox"][0]
    assert rec["size"] == 10 and rec["url"] == "/media/raw/Lego%20Star%20Wars/session.mp4"
    status, headers, body = get(server + rec["url"], {"Range": "bytes=0-3"})
    assert status == 206 and body == b"0123"
