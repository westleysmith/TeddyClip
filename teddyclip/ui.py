"""A small local web page for TeddyClip: find clips, review them in the editor,
watch and delete them, and make highlight videos. It only listens on 127.0.0.1, so nothing outside this PC
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

from teddyclip import cli, editing, progress, session
from teddyclip.config import Config

PAGE = Path(__file__).with_name("ui.html")
EDITOR = Path(__file__).with_name("editor.html")
FONTS = Path(__file__).with_name("fonts")  # the logo font, shipped with the app
ARCHIVE = "Archived"  # inside 2 - Clips: sessions put away from the main list
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
        stay_awake(True)
        try:
            with contextlib.redirect_stdout(_Tee(self)):
                self.failed = bool(work())
        except Exception as e:  # a bug, not a bad recording: still show it
            self.write(f"\nSomething went wrong: {e}\n")
            self.failed = True
        finally:
            stay_awake(False)
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


ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def stay_awake(on: bool) -> None:
    """Keep the PC from going to sleep while a job runs. The screen can still
    turn off and lock. Windows ties this to the calling thread, so the job's
    own thread switches it on and back off."""
    if os.name != "nt":
        return
    import ctypes

    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED if on else ES_CONTINUOUS
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except (AttributeError, OSError):
        pass


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


def _raw_file(cfg: Config, name: str) -> Path | None:
    """A recording in Raw recordings named the way the page lists it
    ("Game/file.mp4", with either slash, or "file.mp4"), or None for anything else."""
    parts = [p for p in re.split(r"[\\/]", name) if p]
    if not 1 <= len(parts) <= 2 or any(_plain_name(p) is None for p in parts):
        return None
    path = cfg.paths.inbox.joinpath(*parts).resolve()
    inbox = cfg.paths.inbox.resolve()
    if not path.is_relative_to(inbox) or not path.is_file() or path.suffix.lower() not in cli.VIDEO_SUFFIXES:
        return None
    return path


# Files this server is sending to the page right now (a preview playing).
# Our own open handle must not make a recording look "still being recorded".
_streaming: collections.Counter = collections.Counter()
_streaming_lock = threading.Lock()


def _stream_key(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _ready(path: Path) -> bool:
    """Like cli.is_finished, but a recording whose preview this server is
    streaming still counts as finished once it has stopped changing."""
    with _streaming_lock:
        ours = _streaming[_stream_key(path)] > 0
    if not ours:
        return cli.is_finished(path)
    try:
        return time.time() - Path(path).stat().st_mtime >= cli.QUIET_SECONDS
    except OSError:
        return False


def _media_url(kind: str, *parts: str) -> str:
    return "/media/" + kind + "/" + "/".join(quote(p) for p in parts)


def _versioned(url: str, file: Path) -> str:
    """Tag a media link with the file's size and time, so a file that changed
    (a clip remade, a highlight redone) is fetched fresh instead of from the
    player's cache."""
    try:
        st = file.stat()
    except OSError:  # deleted a moment ago; the next refresh drops it
        return url
    return f"{url}?v={st.st_size}-{st.st_mtime_ns}"


def _seconds(hms: str) -> float | None:
    """'0:01:43' -> 103.0; None when it is not a time."""
    try:
        total = 0.0
        for part in hms.split(":"):
            total = total * 60 + float(part)
        return total
    except (AttributeError, ValueError):
        return None


def _clip_notes(cfg: Config, session: Path) -> dict[str, dict]:
    """Title, reason and tags per clip file, from moments.csv (kept in the
    working folder; clip folders from older versions have it inside)."""
    csv_path = cli.notes_file(cfg, session.name)
    if not csv_path.is_file():
        csv_path = session / "moments.csv"
    if not csv_path.is_file():
        return {}
    with contextlib.suppress(OSError, csv.Error):
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            return {row.get("file", ""): row for row in csv.DictReader(f) if row.get("file")}
    return {}


def game_name(text: object) -> str | None:
    """A game name usable as a folder name, or None for no game."""
    if not isinstance(text, str):
        return None
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().strip(".").strip()
    return name[:60] or None


def _free_name(path: Path) -> Path:
    n = 2
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        n += 1
    return candidate


def _move(src: Path, dst: Path) -> None:
    """Move a recording. On the same drive this is instant; across drives it is
    copied in chunks (reporting progress), checked, and only then removed. The
    file keeps its date, which names the clip folder and is how TeddyClip tells
    a finished recording from one still being written."""
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass  # a different drive: copy instead
    stat = src.stat()
    part = dst.with_name(dst.name + ".part")
    try:
        with src.open("rb") as fin, part.open("wb") as fout:
            done = 0
            while chunk := fin.read(8 * CHUNK):
                fout.write(chunk)
                done += len(chunk)
                progress.step(done / stat.st_size if stat.st_size else 1.0)
        if part.stat().st_size != stat.st_size:
            raise OSError("the copy came out a different size")
        os.utime(part, (stat.st_atime, stat.st_mtime))
        os.replace(part, dst)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    src.unlink()


def add_recordings(files: list[Path], game: str | None, cfg: Config) -> int:
    """Move recordings into the inbox, inside a folder named after the game
    when there is one. Returns the number that could not be moved."""
    dest = cfg.paths.inbox / game if game else cfg.paths.inbox
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for n, src in enumerate(files):
        with progress.band(n / len(files), (n + 1) / len(files), f"Adding {src.name}"):
            print(f"Adding {src.name} to Raw recordings" + (f" under {game}" if game else ""))
            try:
                _move(src, _free_name(dest / src.name))
            except OSError as e:
                print(f"Could not add {src.name}: {e}")
                failed += 1
    print("Added. Click Find clips when you are ready." if not failed else "Some recordings could not be added.")
    return failed


def _games(cfg: Config, sessions: list[dict]) -> list[str]:
    """Games to offer when adding recordings: recently used first, then the
    games TeddyClip knows from config.yaml."""
    seen: dict[str, str] = {}
    recent = [s["name"].split(" ", 1)[1].split(" (")[0] for s in sessions if " " in s["name"]]
    folders = [d.name for d in cfg.paths.inbox.iterdir() if d.is_dir()] if cfg.paths.inbox.is_dir() else []
    for name in recent + folders + [g.title() for g in cfg.games]:
        seen.setdefault(name.lower(), name)
    return list(seen.values())


def state(cfg: Config, job: Job) -> dict:
    paths = cfg.paths
    inbox = []
    if paths.inbox.is_dir():
        for p in sorted(paths.inbox.rglob("*")):
            if p.is_file() and p.suffix.lower() in cli.VIDEO_SUFFIXES:
                rel = p.relative_to(paths.inbox)
                inbox.append({"name": str(rel), "ready": _ready(p),
                              "size": p.stat().st_size, "url": _media_url("raw", *rel.parts)})
    sessions = []
    if paths.clips.is_dir():
        folders = [d for d in paths.clips.iterdir() if d.is_dir() and d.name != ARCHIVE]
        for folder in sorted(folders, key=lambda d: d.stat().st_mtime, reverse=True):
            notes = _clip_notes(cfg, folder)
            found = session.load(cfg, folder.name)
            made = _made_rows(found) if found else {}
            clips = []
            for clip in sorted(folder.glob("*.mp4"), key=lambda p: p.name):
                row = made.get(clip.name) or notes.get(clip.name, {})
                title = row.get("title") or clip.stem.split(" - ", 1)[-1]
                start, end = _seconds(row.get("start")), _seconds(row.get("end"))
                clips.append({"file": clip.name, "title": title, "why": row.get("why", ""),
                              "kind": row.get("kind", ""), "start": row.get("start", ""),
                              "length": round(end - start) if start is not None and end is not None else None,
                              "events": [e.strip() for e in row.get("events", "").split(";") if e.strip()],
                              "url": _versioned(_media_url("clips", folder.name, clip.name), clip),
                              "edit": clip.name in made})
            highlight = paths.highlights / f"{folder.name}.mp4"
            sessions.append({"name": folder.name, "clips": clips,
                             "editable": found is not None,
                             "suggestions": _suggestion_rows(found, folder) if found else [],
                             "incomplete": "(incomplete" in folder.name,
                             "highlight": _versioned(_media_url("highlights", highlight.name), highlight)
                             if highlight.is_file() else None})
    archived = []
    shelf = paths.clips / ARCHIVE
    if shelf.is_dir():
        for folder in sorted((d for d in shelf.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True):
            archived.append({"name": folder.name, "clips": sum(1 for _ in folder.glob("*.mp4"))})
    settings = load_settings(cfg)
    return {"inbox": inbox, "sessions": sessions, "archived": archived,
            "games": _games(cfg, sessions + archived), "job": job.state(),
            "settings": settings, "auto_status": auto_status(cfg, job, settings)}


def _clock(seconds: float) -> str:
    """103.4 -> "0:01:43", the way moments.csv writes times."""
    hours, rest = divmod(max(0, round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _made_rows(found: dict) -> dict[str, dict]:
    """Clips made in the editor, keyed by file, shaped like moments.csv rows."""
    kinds = {s["id"]: s for s in found.get("suggestions", [])}
    rows = {}
    for m in found.get("made", []):
        picked = kinds.get(m.get("suggestion"), {})
        rows[m["file"]] = {"title": m.get("title", ""), "start": _clock(m["start"]), "end": _clock(m["end"]),
                           "kind": picked.get("kind", ""), "why": picked.get("why", ""),
                           "events": ";".join(picked.get("events", []))}
    return rows


def _suggestion_rows(found: dict, folder: Path) -> list[dict]:
    """A session's suggestions for the main screen, each marked made when a
    clip made from it is still in the clip folder."""
    done = {m.get("suggestion") for m in found.get("made", []) if (folder / m["file"]).is_file()}
    return [{"id": s["id"], "start": s["start"], "end": s["end"], "kind": s["kind"], "title": s["title"],
             "made": s["id"] in done} for s in found.get("suggestions", [])]


def _free_dir(path: Path) -> Path:
    n, candidate = 2, path
    while candidate.exists():
        candidate = path.with_name(f"{path.name} ({n})")
        n += 1
    return candidate


def archive_session(cfg: Config, name: str, back: bool = False) -> Path:
    """Move a clip folder into 2 - Clips/Archived (or back out with back=True),
    so finished sessions stop crowding the window. Nothing is deleted."""
    shelf = cfg.paths.clips / ARCHIVE
    src = (shelf if back else cfg.paths.clips) / name
    if not src.is_dir():
        raise FileNotFoundError(name)
    dst = _free_dir((cfg.paths.clips if back else shelf) / name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    if dst.name != name:  # restored next to a newer session: its own files follow the new name
        notes = session.session_dir(cfg, name)
        if notes.is_dir() and not session.session_dir(cfg, dst.name).exists():
            notes.rename(session.session_dir(cfg, dst.name))
            data = session.load(cfg, dst.name)
            if data is not None:
                preview = data.get("preview")
                if preview:
                    preview = str(session.session_dir(cfg, dst.name) / Path(preview).name)
                session.save(cfg, {**data, "name": dst.name, "preview": preview})
    return dst


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

        def _from_elsewhere(self) -> bool:
            """A request whose Host is not this server. A web page that points
            its own domain at 127.0.0.1 (DNS rebinding) sends its own Host, so
            it cannot read clips or transcripts."""
            port = self.server.server_address[1]
            return self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}")

        def do_GET(self) -> None:
            if self._from_elsewhere():
                return self._error(HTTPStatus.FORBIDDEN, "not allowed")
            path = unquote(urlparse(self.path).path)
            if path == "/":
                body = PAGE.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/edit":
                body = EDITOR.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/state":
                self._json(state(cfg, job))
            elif path.startswith("/api/session/"):
                self._session(path[len("/api/session/"):])
            elif path.startswith("/media/"):
                self._media(path.split("/")[2:])
            elif path.startswith("/fonts/"):
                name = _plain_name(path[len("/fonts/"):])
                font = FONTS / name if name and name.lower().endswith((".ttf", ".woff2")) else None
                if font is None or not font.is_file():
                    return self._error(HTTPStatus.NOT_FOUND, "not found")
                body = font.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "font/woff2" if name.lower().endswith(".woff2") else "font/ttf")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            else:
                self._error(HTTPStatus.NOT_FOUND, "not found")

        def _session(self, raw: str) -> None:
            name = _plain_name(raw)
            data = session.load(cfg, name) if name else None
            if data is None:
                return self._error(HTTPStatus.NOT_FOUND, "no such session")
            folder = cfg.paths.clips / name
            for m in data.get("made", []):
                clip = folder / m["file"]
                m["exists"] = clip.is_file()
                m["url"] = _versioned(_media_url("clips", name, m["file"]), clip)
            playing = Path(data.get("preview") or data.get("recording") or "")
            data["recording_url"] = _media_url("recording", name)
            data["recording_ok"] = playing.is_file()
            self._json(data)

        def _media(self, parts: list[str]) -> None:
            names = [_plain_name(p) for p in parts]
            if not names or None in names:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            if parts[0] == "raw" and len(names) in (2, 3):
                file = cfg.paths.inbox.joinpath(*names[1:])
            elif parts[0] == "clips" and len(names) == 3:
                file = cfg.paths.clips / names[1] / names[2]
            elif parts[0] == "highlights" and len(names) == 2:
                file = cfg.paths.highlights / names[1]
            elif parts[0] == "recording" and len(names) == 2:
                # The path comes from the session file, never from the request.
                data = session.load(cfg, names[1]) or {}
                file = Path(data.get("preview") or data.get("recording") or cfg.paths.notes / "missing")
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
            key = _stream_key(file)
            with _streaming_lock:
                _streaming[key] += 1
            try:
                with contextlib.suppress(ConnectionError), file.open("rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(CHUNK, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            finally:
                with _streaming_lock:
                    _streaming[key] -= 1
                    if _streaming[key] <= 0:
                        del _streaming[key]

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if self._from_elsewhere():
                return self._error(HTTPStatus.FORBIDDEN, "not allowed")
            # Only TeddyClip's own page may act. A web page from elsewhere that
            # tries to post here carries its own Origin and is refused.
            port = self.server.server_address[1]
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                return self._error(HTTPStatus.FORBIDDEN, "not allowed")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except (ValueError, json.JSONDecodeError):
                return self._error(HTTPStatus.BAD_REQUEST, "bad request")
            if not isinstance(data, dict):
                return self._error(HTTPStatus.BAD_REQUEST, "bad request")

            if path == "/api/add":
                names = data.get("files")
                if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
                    return self._error(HTTPStatus.BAD_REQUEST, "no recordings chosen")
                files = [Path(n) for n in names]
                bad = [f.name for f in files if not (f.is_absolute() and f.is_file()
                                                      and f.suffix.lower() in cli.VIDEO_SUFFIXES)]
                if bad:
                    return self._error(HTTPStatus.BAD_REQUEST,
                                       f"Only .mp4 and .mkv recordings can be added ({', '.join(bad)})")
                game = game_name(data.get("game"))
                if not job.start("Adding recordings", lambda: add_recordings(files, game, cfg)):
                    return self._error(HTTPStatus.CONFLICT, "TeddyClip is busy; try again when it is done")
                return self._json({"ok": True})
            if path == "/api/process":
                only = data.get("files")
                if only is not None:
                    # Names as the page lists them ("Game/file.mp4" or "file.mp4"),
                    # and only ever inside Raw recordings.
                    inbox = cfg.paths.inbox.resolve()
                    if (not isinstance(only, list) or not only
                            or not all(isinstance(n, str) and _raw_file(cfg, n) for n in only)):
                        return self._error(HTTPStatus.BAD_REQUEST, "pick recordings from Raw recordings")
                    only = [str(_raw_file(cfg, n).relative_to(inbox)) for n in only]
                if not job.start("Finding clips", lambda: cli.process_inbox(cfg, only)):
                    return self._error(HTTPStatus.CONFLICT, "TeddyClip is already busy")
                return self._json({"ok": True})
            if path == "/api/cut":
                name = _plain_name(data.get("session"))
                title, replace, suggestion = data.get("title", ""), data.get("replace"), data.get("suggestion")
                if name is None or not isinstance(title, str):
                    return self._error(HTTPStatus.BAD_REQUEST, "That session or title is not valid.")
                if suggestion is not None and (isinstance(suggestion, bool) or not isinstance(suggestion, int)):
                    suggestion = None
                try:
                    clip = editing.cut_clip(cfg, name, data.get("start"), data.get("end"), title,
                                            replace=replace, suggestion=suggestion)
                except editing.CutError as e:
                    return self._error(HTTPStatus.BAD_REQUEST, str(e))
                except (OSError, RuntimeError) as e:
                    return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"The clip could not be made: {e}")
                return self._json({"file": clip.name,
                                   "url": _versioned(_media_url("clips", name, clip.name), clip)})
            if path == "/api/highlight":
                session = _plain_name(data.get("session"))
                if session is None or not (cfg.paths.clips / session).is_dir():
                    return self._error(HTTPStatus.BAD_REQUEST, "no such clip folder")
                if not job.start(f"Making the highlight for {session}",
                                 lambda: cli.highlight(cfg.paths.clips / session, cfg)):
                    return self._error(HTTPStatus.CONFLICT, "TeddyClip is already busy")
                return self._json({"ok": True})
            if path == "/api/settings":
                settings = load_settings(cfg)
                if "auto" in data:
                    if not isinstance(data["auto"], bool):
                        return self._error(HTTPStatus.BAD_REQUEST, "auto must be true or false")
                    settings["auto"] = data["auto"]
                if "auto_game" in data:
                    settings["auto_game"] = game_name(data["auto_game"]) or ""
                save_settings(cfg, settings)
                if settings["auto"]:
                    auto_tick(cfg, job)  # do not wait for the first look
                return self._json(settings)
            if path in ("/api/archive", "/api/unarchive"):
                session = _plain_name(data.get("session"))
                if session is None or session == ARCHIVE:
                    return self._error(HTTPStatus.BAD_REQUEST, "no such clip folder")
                try:
                    archive_session(cfg, session, back=path == "/api/unarchive")
                except FileNotFoundError:
                    return self._error(HTTPStatus.NOT_FOUND, "that clip folder is gone")
                except OSError as e:
                    return self._error(HTTPStatus.INTERNAL_SERVER_ERROR,
                                       f"Could not move it (is a clip open somewhere?): {e}")
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
                           "archived": cfg.paths.clips / ARCHIVE,
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


def make_server(cfg: Config, port: int = PORT, watch: bool = False) -> ThreadingHTTPServer:
    """The TeddyClip page's server. watch=True also starts automatic mode's
    watcher, which runs while the server does."""
    cfg.paths.ensure()
    job = Job()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, job))
    server.daemon_threads = True
    if watch:
        threading.Thread(target=_watch, args=(cfg, job), daemon=True).start()
    return server


# Automatic mode: make clips as soon as a recording lands in Raw recordings.

AUTO_CHECK_SECONDS = 10
DEFAULT_SETTINGS = {"auto": False, "auto_game": ""}


def _settings_file(cfg: Config) -> Path:
    return cfg.paths.cache / "settings.json"


def load_settings(cfg: Config) -> dict:
    settings = dict(DEFAULT_SETTINGS)
    with contextlib.suppress(OSError, ValueError, TypeError):
        saved = json.loads(_settings_file(cfg).read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            settings["auto"] = saved.get("auto") is True
            settings["auto_game"] = game_name(saved.get("auto_game")) or ""
    return settings


def save_settings(cfg: Config, settings: dict) -> None:
    path = _settings_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(settings), encoding="utf-8")
    os.replace(tmp, path)


def _raw_recordings(cfg: Config) -> list[Path]:
    inbox = cfg.paths.inbox
    if not inbox.is_dir():
        return []
    return [p for p in inbox.rglob("*") if p.is_file() and p.suffix.lower() in cli.VIDEO_SUFFIXES]


def auto_status(cfg: Config, job: Job, settings: dict) -> str:
    """What automatic mode is doing, in plain words, for the page."""
    if not settings["auto"]:
        return ""
    if job.running:
        return "Working on a recording now."
    files = _raw_recordings(cfg)
    if any(not cli.is_finished(p) for p in files):
        return "Waiting for OBS to finish the recording, so your game is not slowed down."
    return "Watching 1 - Raw recordings. New recordings are clipped as soon as they land."


def auto_tick(cfg: Config, job: Job) -> str:
    """One look at Raw recordings for automatic mode: when it is on, nothing
    is running, and every recording there is finished (OBS has stopped
    writing), file loose recordings under the chosen game and make clips.
    Waiting while anything is still being written keeps a new recording
    session from being slowed down. Returns what it did."""
    settings = load_settings(cfg)
    if not settings["auto"]:
        return "off"
    if job.running:
        return "busy"
    files = _raw_recordings(cfg)
    if not files:
        return "nothing"
    if any(not cli.is_finished(p) for p in files):
        return "recording"
    game = settings["auto_game"]
    if game:
        loose = [p for p in files if p.parent == cfg.paths.inbox]
        if loose:
            (cfg.paths.inbox / game).mkdir(parents=True, exist_ok=True)
        for p in loose:  # same folder tree, so this is an instant rename
            os.replace(p, _free_name(cfg.paths.inbox / game / p.name))
    return "started" if job.start("Finding clips (automatic)", lambda: cli.process_inbox(cfg)) else "busy"


def _watch(cfg: Config, job: Job) -> None:
    while True:
        time.sleep(AUTO_CHECK_SECONDS)
        try:
            auto_tick(cfg, job)
        except Exception:  # a locked or vanished file: look again next time
            pass


def serve(cfg: Config, port: int = PORT, open_browser: bool = True) -> int:
    url = f"http://127.0.0.1:{port}/"
    try:
        server = make_server(cfg, port, watch=True)
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
