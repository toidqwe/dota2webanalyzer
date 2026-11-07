"""Lightweight stdlib web server for the Dota 2 replay analyst."""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data"
CACHE = DATA / "cache"
REPLAYS = DATA / "replays"
CACHE.mkdir(parents=True, exist_ok=True)
REPLAYS.mkdir(parents=True, exist_ok=True)
ENGINE_VERSION = 10
KEEP_REPLAYS = os.environ.get("KEEP_REPLAYS", "").strip() in ("1", "true", "yes")

sys.path.insert(0, str(ROOT))
from analyzer import AnalysisError, analyze_match  # noqa: E402

OPENDOTA = "https://api.opendota.com/api/matches/{}"
API_KEY = os.environ.get("OPENDOTA_API_KEY", "").strip()
MAX_BODY = 14 * 1024 * 1024
HISTORY_FILE = CACHE / "index.json"

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

_lock = threading.Lock()
_memory_cache: dict[str, dict] = {}
_jobs: dict[int, dict] = {}
_parse_lock = threading.Lock()


def read_json(path: Path, default=None):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    tmp.replace(path)


def fetch_opendota(match_id: int, force: bool = False) -> dict:
    cached = CACHE / f"{match_id}.json"
    if cached.exists() and not force:
        raw = read_json(cached)
        if raw:
            return raw
    request = urllib.request.Request(
        OPENDOTA.format(match_id),
        headers={
            "User-Agent": "ota-replay-analyst/1.0",
            **({"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise AnalysisError("Сервис ограничил частоту запросов. Подождите минуту и повторите.", 429) from exc
        if exc.code == 404:
            raise AnalysisError("Матч не найден. Проверьте ID.", 404) from exc
        raise AnalysisError(f"Сервис матчей вернул ошибку {exc.code}. Попробуйте позже.", 502) from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AnalysisError("Не удалось связаться с сервисом матчей. Проверьте интернет.", 502) from exc
    if not isinstance(raw, dict) or not raw.get("match_id"):
        raise AnalysisError("Сервис не вернул матч. Проверьте ID.", 404)
    write_json(cached, raw)
    return raw


def analyze_id(match_id: int) -> tuple[dict, bool]:
    analysis_path = CACHE / f"{match_id}.analysis.json"
    raw_path = CACHE / f"{match_id}.json"
    if analysis_path.exists() and raw_path.exists():
        if analysis_path.stat().st_mtime >= raw_path.stat().st_mtime:
            cached = read_json(analysis_path)
            if cached and cached.get("ok") and (cached.get("method") or {}).get("version") == ENGINE_VERSION:
                return cached, True
    raw = fetch_opendota(match_id)
    analysis = analyze_match(raw)
    write_json(analysis_path, analysis)
    _remember(analysis)
    return analysis, False


def analyze_raw(raw: dict) -> dict:
    analysis = analyze_match(raw)
    match_id = analysis.get("match", {}).get("id")
    if match_id:
        write_json(CACHE / f"{match_id}.json", raw)
        write_json(CACHE / f"{match_id}.analysis.json", analysis)
        _remember(analysis)
    return analysis


def _remember(analysis: dict) -> None:
    with _lock:
        history = read_json(HISTORY_FILE, []) or []
        match = analysis["match"]
        heroes = [{"name": p["hero"]["name"], "img": p["hero"]["img"]} for p in analysis["players"]]
        score = match["score"]
        entry = {
            "id": match["id"],
            "date": match.get("date"),
            "duration": match.get("duration_label"),
            "score": f"{score['radiant']}:{score['dire']}",
            "winner": match["winner"],
            "winner_word": match["winner_word"],
            "heroes": heroes,
            "ts": int(time.time()),
        }
        history = [h for h in history if h.get("id") != entry["id"]]
        history.insert(0, entry)
        write_json(HISTORY_FILE, history[:12])


# ---------------------------------------------------------------- replay jobs
def _job_public(match_id: int, with_analysis: bool = False) -> dict | None:
    with _lock:
        job = _jobs.get(match_id)
        if not job:
            return None
        out = {
            "id": match_id,
            "status": job["status"],
            "stage": job["stage"],
            "progress": job["progress"],
            "message": job["message"],
            "started": job["started"],
            "elapsed": max(0, int(time.time() - job["started"])),
            "error": job.get("error"),
            "code": job.get("code"),
        }
        if with_analysis and job.get("analysis"):
            out["analysis"] = job["analysis"]
        return out


def _set_job(match_id: int, **fields) -> None:
    with _lock:
        job = _jobs.get(match_id)
        if not job:
            return
        job.update(fields)
        job["updated"] = time.time()


def start_replay_job(match_id: int, force: bool = False) -> dict:
    existing = None
    with _lock:
        existing = _jobs.get(match_id)
        if not (existing and existing["status"] in ("queued", "running")):
            _jobs[match_id] = {
                "status": "queued",
                "stage": "queued",
                "progress": 2,
                "message": "Ставим матч в очередь на парс",
                "started": time.time(),
                "updated": time.time(),
                "error": None,
                "code": None,
                "analysis": None,
                "force": bool(force),
            }
            existing = None
    if existing:
        return _job_public(match_id) or {}
    threading.Thread(target=_replay_worker, args=(match_id,), daemon=True).start()
    return _job_public(match_id) or {}


def _normalize_replay_url(url: str) -> str:
    """OpenDota sometimes returns regional (often dead) CDN hosts; Valve's canonical host works."""
    if not url:
        return url
    match = re.match(r"https?://replay(\d+)\.dota2\.com\.cn/(.+)$", url)
    if match:
        return f"http://replay{match.group(1)}.valve.net/{match.group(2)}"
    if url.startswith("https://replay") and ".valve.net/" in url:
        return "http://" + url[len("https://") :]
    return url


def _replay_worker(match_id: int) -> None:
    replay_path: Path | None = None
    try:
        with _lock:
            force = bool((_jobs.get(match_id) or {}).get("force"))
        cached = read_json(CACHE / f"{match_id}.analysis.json")
        if not force and cached and cached.get("ok") and (cached.get("method") or {}).get("version") == ENGINE_VERSION:
            _set_job(match_id, status="done", stage="done", progress=100, message="Готово", analysis=cached)
            return

        _set_job(match_id, status="running", stage="fetch", progress=8, message="Проверяем матч и ищем реплей")
        try:
            raw = fetch_opendota(match_id, force=True)
        except AnalysisError:
            raw = fetch_opendota(match_id, force=False)
        players = raw.get("players") or []
        if players and players[0].get("gold_t") and not force:
            _set_job(match_id, stage="stats", progress=82, message="Матч уже распарсен — считаем статистику")
            analysis = analyze_match(raw)
            _finish_job(match_id, raw, analysis)
            return

        replay_url = _normalize_replay_url(raw.get("replay_url") or "")
        if not replay_url:
            raise AnalysisError(
                "Сервис не отдал ссылку на реплей: скорее всего, Valve уже удалила файл. "
                "Реплеи хранятся ограниченное время, обычно около недели.",
                409,
                code="no_replay",
            )

        try:
            import gem  # imported lazily: server still starts without the parser
        except ImportError as exc:
            raise AnalysisError(
                "Локальный парсер не установлен. Выполните «pip install -r requirements.txt» и перезапустите сервер.",
                500,
                code="parser_missing",
            ) from exc

        _set_job(match_id, stage="download", progress=14, message="Скачиваем реплей с серверов Valve (~100 МБ)")
        try:
            replay_path = gem.download_and_decompress(match_id, replay_url, REPLAYS)
        except urllib.error.HTTPError:
            raise
        except Exception as exc:  # noqa: BLE001 - network/decompress failure
            raise AnalysisError(
                "Не удалось скачать или распаковать реплей. Попробуйте ещё раз через минуту.",
                502,
                code="download_failed",
            ) from exc

        _set_job(match_id, stage="parse", progress=38, message="Парсим реплей — обычно это 2–10 минут")
        with _parse_lock:
            _set_job(match_id, stage="parse", progress=40, message="Парсим реплей — обычно это 2–10 минут")
            parsed = gem.parse(replay_path)

        _set_job(match_id, stage="stats", progress=88, message="Считаем экономику, смерти и переломные моменты")
        from analyzer.from_replay import to_opendota_dict

        data = to_opendota_dict(
            parsed,
            meta={
                "start_time": raw.get("start_time"),
                "game_mode": raw.get("game_mode"),
                "lobby_type": raw.get("lobby_type"),
                "patch": raw.get("patch"),
            },
        )
        rank_by_account = {
            str(p.get("account_id")): p for p in (raw.get("players") or []) if p.get("account_id")
        }
        for player in data.get("players") or []:
            source = rank_by_account.get(str(player.get("account_id")))
            if source:
                player["rank_tier"] = source.get("rank_tier") or 0
                player["computed_mmr"] = source.get("computed_mmr")
        analysis = analyze_match(data)
        _finish_job(match_id, data, analysis)
    except AnalysisError as exc:
        _set_job(match_id, status="error", stage="error", progress=0, message=exc.message, error=exc.message, code=exc.code)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            message = (
                "Реплей уже недоступен: Valve удалила файл с серверов. "
                "Реплеи живут ограниченное время (обычно около недели), поэтому старые матчи так разобрать нельзя."
            )
            code = "replay_expired"
        else:
            message = f"Не удалось скачать реплей (HTTP {exc.code}). Попробуйте позже."
            code = "download_failed"
        _set_job(match_id, status="error", stage="error", progress=0, message=message, error=message, code=code)
    except Exception as exc:  # noqa: BLE001 - user-facing worker
        traceback.print_exc()
        name = type(exc).__name__
        if name in ("TruncatedReplayError", "ReplayDataError"):
            message = "Реплей повреждён или скачался не полностью. Попробуйте ещё раз."
            code = "bad_replay"
        else:
            message = "Не удалось распарсить реплей. Попробуйте ещё раз через минуту."
            code = "parse_failed"
        _set_job(match_id, status="error", stage="error", progress=0, message=message, error=message, code=code)
    finally:
        if not KEEP_REPLAYS:
            for candidate in list(REPLAYS.glob(f"{match_id}.dem*")):
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass


def _finish_job(match_id: int, raw: dict, analysis: dict) -> None:
    write_json(CACHE / f"{match_id}.json", raw)
    write_json(CACHE / f"{match_id}.analysis.json", analysis)
    _remember(analysis)
    _set_job(match_id, status="done", stage="done", progress=100, message="Отчёт готов", analysis=analysis)


def demo_analysis() -> dict:
    path = DATA / "demo_match.json"
    if not path.exists():
        raise AnalysisError("Демо-матч не найден в data/demo_match.json", 500)
    raw = read_json(path)
    if not raw:
        raise AnalysisError("Не удалось прочитать демо-матч", 500)
    if "demo" not in _memory_cache:
        _memory_cache["demo"] = analyze_match(raw)
    return _memory_cache["demo"]


class Handler(BaseHTTPRequestHandler):
    server_version = "OTA/1.0"

    def log_message(self, fmt, *args):  # quiet, structured enough
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------------ helpers
    def _send(self, status: int, body: bytes, content_type: str, cache: str = "no-store"):
        if len(body) > 1024 and "gzip" in self.headers.get("Accept-Encoding", ""):
            body = gzip.compress(body, 6)
            encoding = "gzip"
        else:
            encoding = None
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: dict, status: int = 200, cache: str = "no-store"):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", cache)

    def _error(self, message: str, status: int = 400, code: str = "error"):
        self._json({"ok": False, "error": message, "status": status, "code": code}, status)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise AnalysisError("Пустое тело запроса", 400)
        if length > MAX_BODY:
            raise AnalysisError("Слишком большой файл (максимум 14 МБ)", 413)
        return self.rfile.read(length)

    # -------------------------------------------------------------------- routes
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._json({"ok": True, "service": "ota", "time": int(time.time())})
                return
            if path == "/api/demo":
                self._json({"ok": True, "analysis": demo_analysis(), "cached": True})
                return
            if path == "/api/history":
                self._json({"ok": True, "items": read_json(HISTORY_FILE, []) or []})
                return
            if path == "/api/analyze":
                match_id = (query.get("id") or [""])[0]
                if not re.fullmatch(r"\d{6,12}", match_id or ""):
                    self._error("Укажите корректный ID матча", 400)
                    return
                analysis, cached = analyze_id(int(match_id))
                self._json({"ok": True, "analysis": analysis, "cached": cached})
                return
            if path.startswith("/api/replay/"):
                match_id = path.rsplit("/", 1)[-1]
                if not re.fullmatch(r"\d{6,12}", match_id or ""):
                    self._error("Укажите корректный ID матча", 400)
                    return
                job = _job_public(int(match_id), with_analysis=True)
                if not job:
                    self._error("Задача парса не найдена", 404, "no_job")
                    return
                self._json({"ok": True, "job": job})
                return
            if path == "/api/replay":
                match_id = (query.get("id") or [""])[0]
                if not re.fullmatch(r"\d{6,12}", match_id or ""):
                    self._error("Укажите корректный ID матча", 400)
                    return
                force = (query.get("force") or ["0"])[0] in ("1", "true")
                self._json({"ok": True, "job": start_replay_job(int(match_id), force=force)})
                return
            if path.startswith("/api/match/"):
                match_id = path.rsplit("/", 1)[-1]
                if not re.fullmatch(r"\d{6,12}", match_id or ""):
                    self._error("Укажите корректный ID матча", 400)
                    return
                analysis, cached = analyze_id(int(match_id))
                self._json({"ok": True, "analysis": analysis, "cached": cached})
                return
            if path.startswith("/api/"):
                self._error("Неизвестный метод API", 404)
                return
            self._static(path)
        except AnalysisError as exc:
            self._error(exc.message, exc.status, exc.code)
        except Exception as exc:  # pragma: no cover - defensive
            sys.stderr.write(f"unhandled GET error: {exc!r}\n")
            self._error("Внутренняя ошибка сервера", 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/replay":
                body = self._body()
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except (UnicodeDecodeError, ValueError):
                    self._error("Некорректный JSON", 400)
                    return
                match_id = str(payload.get("id") or payload.get("match_id") or (query.get("id") or [""])[0])
                if not re.fullmatch(r"\d{6,12}", match_id):
                    self._error("Укажите корректный ID матча", 400)
                    return
                self._json({"ok": True, "job": start_replay_job(int(match_id), force=bool(payload.get("force")))})
                return
            if parsed.path == "/api/analyze":
                body = self._body()
                try:
                    raw = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self._error("Файл не является корректным JSON", 400)
                    return
                if isinstance(raw, dict) and isinstance(raw.get("match"), dict) and "players" not in raw:
                    raw = raw["match"]
                if not isinstance(raw, dict) or "players" not in raw:
                    self._error("Это не JSON матча: нет поля players", 400)
                    return
                analysis = analyze_raw(raw)
                self._json({"ok": True, "analysis": analysis, "cached": False})
                return
            self._error("Неизвестный метод API", 404)
        except AnalysisError as exc:
            self._error(exc.message, exc.status, exc.code)
        except Exception as exc:  # pragma: no cover
            sys.stderr.write(f"unhandled POST error: {exc!r}\n")
            self._error("Внутренняя ошибка сервера", 500)

    def _static(self, path: str):
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (WEB / rel).resolve()
        try:
            candidate.relative_to(WEB.resolve())
        except ValueError:
            self._error("Недопустимый путь", 403)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists() or not candidate.is_file():
            index = WEB / "index.html"
            if index.exists():
                self._send(200, index.read_bytes(), STATIC_TYPES[".html"], "no-cache")
            else:
                self._error("Файл не найден", 404)
            return
        suffix = candidate.suffix.lower()
        content_type = STATIC_TYPES.get(suffix, "application/octet-stream")
        cache = "public, max-age=604800" if suffix in (".png", ".jpg", ".webp", ".svg", ".woff2") else "no-cache"
        self._send(200, candidate.read_bytes(), content_type, cache)


def main():
    port = int(os.environ.get("PORT", "8765"))
    for arg in sys.argv[1:]:
        if arg.isdigit():
            port = int(arg)
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"OTA server: http://127.0.0.1:{port} (bind {host})")
    print(f"Demo match: /api/demo")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

