import json
import subprocess
import sys
import types
import urllib.request

import pytest

from teddyclip import app, media, ui


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


def fake_webview(seen):
    """Stands in for pywebview: records the window and, while 'open', asks the
    page for its state the way the real window would."""
    mod = types.ModuleType("webview")

    def create_window(title, url, **kwargs):
        seen["title"], seen["url"], seen["kwargs"] = title, url, kwargs
        return types.SimpleNamespace(events=types.SimpleNamespace(shown=FakeEvent()), native=None)

    def start():
        with urllib.request.urlopen(seen["url"] + "api/state") as r:
            seen["state"] = json.loads(r.read())

    mod.create_window, mod.start = create_window, start
    return mod


def test_window_shows_the_page_and_closing_it_stops_the_server(cfg, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setitem(sys.modules, "webview", fake_webview(seen))
    monkeypatch.setattr(app, "load_config", lambda path: cfg)
    started = []
    real = ui.make_server
    # A free port for the test server; the window URL still names the usual port.
    monkeypatch.setattr(ui, "make_server", lambda c, port: started.append(real(c, 0)) or started[-1])

    def start():  # while the window is "open", the page can reach the server
        port = started[0].server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state") as r:
            seen["state"] = json.loads(r.read())

    sys.modules["webview"].start = start
    assert app.main() == 0
    assert seen["title"] == "TeddyClip" and seen["url"] == "http://127.0.0.1:8765/"
    assert "sessions" in seen["state"]
    with pytest.raises(OSError):  # the server is closed once the window closes
        urllib.request.urlopen(f"http://127.0.0.1:{started[0].server_address[1]}/api/state", timeout=2)


def test_second_window_reuses_the_running_teddyclip(cfg, monkeypatch):
    seen = {}
    monkeypatch.setitem(sys.modules, "webview", fake_webview(seen))
    monkeypatch.setattr(app, "load_config", lambda path: cfg)
    srv = ui.make_server(cfg, port=0)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(ui, "PORT", srv.server_address[1])

    def busy(c, port):
        raise OSError("address in use")
    monkeypatch.setattr(ui, "make_server", busy)
    try:
        assert app.main() == 0 and "sessions" in seen["state"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_config_found_in_the_install_folder(tmp_path, monkeypatch):
    install = tmp_path / "TeddyClip-app"
    (install / ".venv").mkdir(parents=True)
    (install / "config.yaml").write_text("people: [A, B]\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(install / ".venv"))
    assert app._config_path() == install / "config.yaml"


def test_windowless_output_goes_to_a_log(cfg, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    app._quiet_output(cfg)
    print("Downloading model...")
    sys.stderr.write("progress 50%\n")
    sys.stdout.flush()
    text = (cfg.paths.cache / "teddyclip.log").read_text(encoding="utf-8")
    assert "Downloading model..." in text and "progress 50%" in text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_ffmpeg_runs_without_flashing_a_console(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(kw) or
                        subprocess.CompletedProcess(cmd, 0, b"", b""))
    media._run(["ffmpeg", "-version"], "check")
    assert calls[0]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_pick_recordings_opens_the_file_picker_at_videos(monkeypatch, tmp_path):
    asked = {}

    class Window:
        def create_file_dialog(self, kind, directory="", allow_multiple=False, file_types=()):
            asked.update(directory=directory, multiple=allow_multiple, types=file_types)
            return (r"C:\Videos\a.mp4",)

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(OPEN_DIALOG=10))
    monkeypatch.setattr(app.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / "Videos").mkdir()
    api = app.Api()
    api.window = Window()
    assert api.pick_recordings() == [r"C:\Videos\a.mp4"]
    assert asked["directory"] == str(tmp_path / "Videos") and asked["multiple"]
    assert "*.mp4" in asked["types"][0]
