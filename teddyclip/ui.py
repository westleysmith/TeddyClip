"""A small local web page for TeddyClip: make clips, watch and delete them, and
make highlight videos. It only listens on 127.0.0.1, so nothing outside this PC
can reach it, and it uses Python's built-in web server."""

from __future__ import annotations

import collections
import contextlib
import csv
import json
import mimetypes
import os
import re
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from teddyclip import cli, progress
from teddyclip.config import Config

PAGE = Path(__file__).with_name("ui.html")
PORT = 8765
CHUNK = 1 << 20


class Job:
    """One background task at a time (making clips or a highlight), with the
    text it prints kept for the page to show."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name = ""
        self.running = False
        self.failed = False
        self.lines: collections.deque[str] = collections.deque(maxlen=300)
        self._partial = ""
        self.step, self.fraction, self.started, self.finished = "", 0.0, 0.0, 0.0

    def start(self, name: str, work) -> bool:
        with self.lock:
            if self.running:
                return False
            self.name, self.running, self.failed, self._partial = name, True, False, ""
            self.lines.clear()
            self.step, self.fraction, self.started, self.finished = "Starting", 0.0, time.time(), 0.0
        threading.Thread(target=self._run, args=(work,), daemon=True).start()
        return True

    def _run(self, work) -> None:
        progress.listen(self._progress)
        try:
            with contextlib.redirect_stdout(_Tee(self)):
                self.failed = bool(work())
        except Exception as e:  # a bug, not a bad recording: still show it
            self.write(f"\nSomething went wrong: {e}\n")
            self.failed = True
        finally:
            progress.listen(None)
            self.write("\n")
            with self.lock:
                self.finished = time.time()
                if not self.failed:
                    self.fraction = 1.0
            self.running = False

    def _progress(self, step: str, fraction: float) -> None:
        with self.lock:
            if step:
                self.step = step
            self.fraction = max(self.fraction, fraction)  # the bar never jumps backwards

    def write(self, text: str) -> None:
        with self.lock:
            text = self._partial + text.replace("\r", "\n")
            *done, self._partial = text.split("\n")
            self.lines.extend(line for line in done if line.strip())

    def state(self) -> dict:
        with self.lock:
            lines = list(self.lines) + ([self._partial] if self._partial.strip() else [])
            elapsed = ((self.finished or time.time()) - self.started) if self.started else 0.0
            step, fraction = self.step, self.fraction
        return {"name": self.name, "running": self.running, "failed": self.failed, "lines": lines[-80:],
                "step": step, "fraction": round(fraction, 4), "elapsed": round(elapsed, 1)}


class _Tee:
    """Sends printed text to the job log and still to the console window."""

    def __init__(self, job: Job) -> None:
        self.job = job

    def write(self, text: str) -> int:
        self.job.write(text)
        console = sys.__stdout__
        if console is not None:
            with contextlib.suppress(Exception):
                console.write(text)
        return len(text)

    def flush(self) -> None:
        if sys.__stdout__ is not None:
            with contextlib.suppress(Exception):
                sys.__stdout__.flush()


def to_recycle_bin(path: Path) -> None:
    """Delete a file in a way that can be undone: the Windows Recycle Bin, or a
    'Deleted' folder next to it elsewhere."""
    if os.name != "nt":
        bin_dir = path.parent / "Deleted"
        bin_dir.mkdir(exist_ok=True)
        path.replace(bin_dir / path.name)
        return
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    # pFrom is a list ending in two NULs; ctypes adds the second one.
    op = SHFILEOPSTRUCTW(None, FO_DELETE, str(path) + "\0", None,
                         FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI, False, None, None)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0 or path.exists():
        raise OSError(f"could not move {path.name} to the Recycle Bin")


def _plain_name(name: object) -> str | None:
    """A single file or folder name, never a path, so requests stay inside TeddyClip's folders."""
    if not isinstance(name, str) or not name or name != Path(name).name or name.startswith("."):
        return None
    return name


def _media_url(kind: str, *parts: str) -> str:
    return "/media/" + kind + "/" + "/".join(quote(p) for p in parts)


def _clip_notes(session: Path) -> dict[str, dict]:
    csv_path = session / "moments.csv"
    if not csv_path.is_file():
        return {}
    with contextlib.suppress(OSError, csv.Error):
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            return {row.get("file", ""): row for row in csv.DictReader(f) if row.get("file")}
    return {}


def state(cfg: Config, job: Job) -> dict:
    paths = cfg.paths
    inbox = []
    if paths.inbox.is_dir():
        for p in sorted(paths.inbox.rglob("*")):
            if p.is_file() and p.suffix.lower() in cli.VIDEO_SUFFIXES:
                inbox.append({"name": str(p.relative_to(paths.inbox)), "ready": cli.is_finished(p)})
    sessions = []
    if paths.clips.is_dir():
        folders = [d for d in paths.clips.iterdir() if d.is_dir()]
        for folder in sorted(folders, key=lambda d: d.stat().st_mtime, reverse=True):
            notes = _clip_notes(folder)
            clips = []
            for clip in sorted(folder.glob("*.mp4"), key=lambda p: p.name):
                row = notes.get(clip.name, {})
                title = row.get("title") or clip.stem.split(" - ", 1)[-1]
                clips.append({"file": clip.name, "title": title, "why": row.get("why", ""),
                              "kind": row.get("kind", ""), "start": row.get("start", ""),
                              "events": [e.strip() for e in row.get("events", "").split(";") if e.strip()],
                              "url": _media_url("clips", folder.name, clip.name)})
            highlight = paths.highlights / f"{folder.name}.mp4"
            sessions.append({"name": folder.name, "clips": clips,
                             "incomplete": "(incomplete" in folder.name,
                             "highlight": _media_url("highlights", highlight.name) if highlight.is_file() else None})
    return {"inbox": inbox, "sessions": sessions, "job": job.state()}


def make_handler(cfg: Config, job: Job):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TeddyClip"

        def log_message(self, *args) -> None:  # keep the console window readable
            pass

        def _json(self, data, status=HTTPStatus.OK) -> None:
            body = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message: str) -> None:
            self._json({"error": message}, status)

        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path)
            if path == "/":
                body = PAGE.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._json(state(cfg, job))
            elif path.startswith("/media/"):
                self._media(path.split("/")[2:])
            else:
                self._error(HTTPStatus.NOT_FOUND, "not found")

        def _media(self, parts: list[str]) -> None:
            names = [_plain_name(p) for p in parts]
            if not names or None in names:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            if parts[0] == "clips" and len(names) == 3:
                file = cfg.paths.clips / names[1] / names[2]
            elif parts[0] == "highlights" and len(names) == 2:
                file = cfg.paths.highlights / names[1]
            else:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            if not file.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            self._send_file(file)

        def _send_file(self, file: Path) -> None:
            size = file.stat().st_size
            start, end, status = 0, size - 1, HTTPStatus.OK
            wanted = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
            if wanted and size:
                first, last = wanted.groups()
                if first:
                    start, end = int(first), int(last) if last else size - 1
                elif last:
                    start = max(0, size - int(last))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
            self.send_response(status)
            self.send_header("Content-Type", mimetypes.guess_type(file.name)[0] or "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            with contextlib.suppress(ConnectionError), file.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except (ValueError, json.JSONDecodeError):
                return self._error(HTTPStatus.BAD_REQUEST, "bad request")
            if not isinstance(data, dict):
                return self._error(HTTPStatus.BAD_REQUEST, "bad request")

            if path == "/api/process":
                if not job.start("Making clips", lambda: cli.process_inbox(cfg)):
                    return self._error(HTTPStatus.CONFLICT, "TeddyClip is already busy")
                return self._json({"ok": True})
            if path == "/api/highlight":
                session = _plain_name(data.get("session"))
                if session is None or not (cfg.paths.clips / session).is_dir():
                    return self._error(HTTPStatus.BAD_REQUEST, "no such clip folder")
                if not job.start(f"Making the highlight for {session}",
                                 lambda: cli.highlight(cfg.paths.clips / session, cfg)):
                    return self._error(HTTPStatus.CONFLICT, "TeddyClip is already busy")
                return self._json({"ok": True})
            if path == "/api/delete":
                session, file = _plain_name(data.get("session")), _plain_name(data.get("file"))
                if session is None or file is None or not file.lower().endswith(".mp4"):
                    return self._error(HTTPStatus.BAD_REQUEST, "bad clip name")
                clip = cfg.paths.clips / session / file
                if not clip.is_file():
                    return self._error(HTTPStatus.NOT_FOUND, "that clip is already gone")
                try:
                    to_recycle_bin(clip)
                except OSError as e:
                    return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
                return self._json({"ok": True})
            if path == "/api/open":
                folders = {"inbox": cfg.paths.inbox, "clips": cfg.paths.clips,
                           "highlights": cfg.paths.highlights, "done": cfg.paths.done}
                folder = folders.get(data.get("folder"))
                if folder is None:
                    return self._error(HTTPStatus.BAD_REQUEST, "unknown folder")
                session = _plain_name(data.get("session"))
                if session and (folder / session).is_dir():
                    folder = folder / session
                folder.mkdir(parents=True, exist_ok=True)
                if hasattr(os, "startfile"):
                    os.startfile(folder)  # opens File Explorer
                return self._json({"ok": True})
            self._error(HTTPStatus.NOT_FOUND, "not found")

    return Handler


def make_server(cfg: Config, port: int = PORT) -> ThreadingHTTPServer:
    cfg.paths.ensure()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, Job()))
    server.daemon_threads = True
    return server


def serve(cfg: Config, port: int = PORT, open_browser: bool = True) -> int:
    url = f"http://127.0.0.1:{port}/"
    try:
        server = make_server(cfg, port)
    except OSError:
        # Most likely TeddyClip is already open in another window: just show it.
        print(f"TeddyClip seems to be open already. Opening {url}")
        if open_browser:
            webbrowser.open(url)
        return 0
    print(f"TeddyClip is open in your browser at {url}")
    print("Keep this window open while you use TeddyClip. Close it when you are done.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
