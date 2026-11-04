"""TeddyClip as its own window: the TeddyClip page in a native Windows window
(Edge WebView2, built into Windows), with no console and no browser. Closing
the window quits TeddyClip. Started by the teddyclip-app.exe the installer's
shortcut points at."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

from teddyclip import ui
from teddyclip.config import Config, load_config

ICON = Path(__file__).with_name("teddyclip.ico")
APP_ID = "TeddyClip.App"


def _config_path() -> Path | None:
    """config.yaml in the current folder, else the one in the install folder
    (the folder holding .venv), so the app finds it however it is started."""
    here = Path.cwd() / "config.yaml"
    if here.is_file():
        return here
    install = Path(sys.prefix).parent / "config.yaml"
    return install if install.is_file() else None


def _quiet_output(cfg: Config) -> None:
    """A windowless program has no console: send anything printed (download
    progress bars, warnings) to a log file instead of losing it or crashing."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log = cfg.paths.cache / "teddyclip.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log, "a", encoding="utf-8", buffering=1)  # stays open for the app's life
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def _set_taskbar_identity() -> None:
    """Own taskbar button and icon instead of being grouped under Python."""
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass


def _set_window_icon(window) -> None:
    """Put the starburst on the title bar and taskbar (WinForms backend)."""
    try:
        from System import Action
        from System.Drawing import Icon

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))
    except Exception:
        pass  # cosmetic only


class Api:
    """What the page can ask the window for (window.pywebview.api in the page).

    pywebview hands every public attribute of this object to the page, walking
    into each one. The window is kept in `_window` (pywebview skips names that
    start with an underscore): as a public attribute, pywebview walked into the
    whole Windows form behind it, whose properties lead back to themselves,
    and froze the window doing it."""

    def __init__(self, memory: Path | None = None) -> None:
        self._window = None
        self._memory = memory  # remembers the folder recordings were last added from

    def _start_folder(self) -> Path:
        """Where the picker opens: the folder recordings were last added from,
        else Videos (where OBS records by default)."""
        try:
            last = Path(json.loads(self._memory.read_text(encoding="utf-8"))["last_folder"])
            if last.is_dir():
                return last
        except (AttributeError, OSError, ValueError, KeyError, TypeError):
            pass
        videos = Path.home() / "Videos"
        return videos if videos.is_dir() else Path.home()

    def pick_recordings(self) -> list[str]:
        """The Windows file picker, opened where recordings were last added from."""
        import webview

        kind = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        chosen = [str(p) for p in self._window.create_file_dialog(
            kind, directory=str(self._start_folder()), allow_multiple=True,
            file_types=("Recordings (*.mp4;*.mkv)", "All files (*.*)")) or []]
        if chosen and self._memory is not None:
            try:
                self._memory.parent.mkdir(parents=True, exist_ok=True)
                self._memory.write_text(json.dumps({"last_folder": str(Path(chosen[0]).parent)}), encoding="utf-8")
            except OSError:
                pass  # only a convenience
        return chosen


def main() -> int:
    import webview

    cfg = load_config(_config_path())
    _quiet_output(cfg)
    _set_taskbar_identity()

    server = None
    try:
        server = ui.make_server(cfg, ui.PORT, watch=True)
    except OSError:
        pass  # TeddyClip is already open: this window shows the same page
    if server is not None:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    api = Api(cfg.paths.cache / "window.json")
    window = webview.create_window("TeddyClip", f"http://127.0.0.1:{ui.PORT}/",
                                   width=1320, height=900, min_size=(760, 560),
                                   background_color="#F3EAD8", js_api=api)
    api._window = window
    window.events.shown += lambda: _set_window_icon(window)
    try:
        webview.start()
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
