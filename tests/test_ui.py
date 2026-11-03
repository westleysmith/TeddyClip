import json
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
    assert (clip["title"], clip["kind"], clip["start"]) == ("Boss fight", "trigger", "0:00:10")
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
    def fake(cfg):
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
    monkeypatch.setattr(cli, "process_inbox", lambda cfg: gate.wait(5) and 0)
    assert post(server + "/api/process", {})[0] == 200
    assert post(server + "/api/highlight", {"session": session.name})[0] == 409
    gate.set()


def test_job_log_handles_carriage_return_progress():
    job = ui.Job()
    job.write("Transcribed up to 1.0s\rTranscribed up to 2.0s")
    job.write("\nMeasuring loudness...\n")
    assert job.state()["lines"] == ["Transcribed up to 1.0s", "Transcribed up to 2.0s", "Measuring loudness..."]
