from __future__ import annotations

import argparse
import hmac
import json
import secrets
import os
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .mission_control import MissionControlService, ProviderUnavailableError
from .research import ResearchUnavailableError


MAX_BODY_BYTES = 1_000_000
WEB_DIR = Path(__file__).with_name("mission_control_web")


def _load_local_env() -> None:
    """Load a simple repository-root .env without adding a runtime dependency."""
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _stealth_enabled() -> bool:
    return os.getenv("SUPERBRAIN_STEALTH_MODE", "1").strip().casefold() in {"1", "true", "yes", "on"}


class MissionControlHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_cls, service: MissionControlService, token: str | None):
        super().__init__(server_address, handler_cls)
        self.service = service
        self.token = token


class MissionControlHandler(BaseHTTPRequestHandler):
    server: MissionControlHTTPServer

    def log_message(self, _format: str, *_args) -> None:
        return

    def _authorized(self) -> bool:
        if self.server.token is None:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return header.startswith(prefix) and hmac.compare_digest(header[len(prefix):], self.server.token)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'",
        )

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        length = int(raw_length)
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise ValueError("Content-Type must be application/json")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._static(WEB_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._static(WEB_DIR / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/styles.css":
            self._static(WEB_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "milestone": "SB-027", "ui_version": "SB-027", "build_version": "SB-028"})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if path == "/api/system/status":
            self._json(HTTPStatus.OK, self.server.service.system_status())
            return
        if path == "/api/missions":
            self._json(HTTPStatus.OK, {"missions": self.server.service.list_missions()})
            return
        if path == "/api/world-model":
            limit = int(parse_qs(urlparse(self.path).query).get("limit", [100])[0])
            self._json(HTTPStatus.OK, {"beliefs": self.server.service.list_world_beliefs(limit)})
            return
        if path == "/api/assurance":
            limit = int(parse_qs(urlparse(self.path).query).get("limit", [50])[0])
            self._json(HTTPStatus.OK, {"runs": self.server.service.list_assurance_runs(limit)})
            return
        if path == "/api/changes":
            query = parse_qs(urlparse(self.path).query)
            limit = int(query.get("limit", [50])[0])
            unack = query.get("unacknowledged", ["0"])[0].casefold() in {"1", "true", "yes", "on"}
            self._json(HTTPStatus.OK, {"changes": self.server.service.list_changes(limit, unacknowledged_only=unack)})
            return
        if path == "/api/autonomy/cycles":
            limit = int(parse_qs(urlparse(self.path).query).get("limit", [20])[0])
            self._json(HTTPStatus.OK, {"cycles": self.server.service.list_autonomy_cycles(limit)})
            return
        if path.startswith("/api/missions/"):
            run_id = path.removeprefix("/api/missions/")
            item = self.server.service.get_mission(run_id)
            if item is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "mission_not_found"})
            else:
                self._json(HTTPStatus.OK, item)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            payload = self._read_json()
            if path == "/api/assurance":
                result = self.server.service.run_assurance(dict(payload.get("observation") or {}), run_id=str(payload.get("run_id") or "assurance-api"))
                self._json(HTTPStatus.OK, result)
                return
            if path == "/api/osint/diagnostics":
                result = self.server.service.run_osint_diagnostics()
                self._json(HTTPStatus.OK, result)
                return
            if path == "/api/autonomy/cycle":
                missions = payload.get("missions")
                if missions is not None and not isinstance(missions, list):
                    raise ValueError("missions must be a JSON array")
                result = self.server.service.run_autonomous_cycle(missions, cycle_id=payload.get("cycle_id"))
                self._json(HTTPStatus.CREATED, result)
                return
            if path == "/api/missions/ask":
                result = self.server.service.execute_interactive_mission(
                    str(payload.get("mission", "")),
                    run_id=payload.get("run_id"),
                )
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path == "/api/missions/research":
                result = self.server.service.execute_research_mission(
                    str(payload.get("mission", "")),
                    run_id=payload.get("run_id"),
                    max_results_per_query=int(payload.get("max_results_per_query", 3)),
                    max_sources=int(payload.get("max_sources", 6)),
                )
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path == "/api/missions/deep-research":
                result = self.server.service.execute_deep_research_mission(
                    str(payload.get("mission", "")),
                    run_id=payload.get("run_id"),
                    max_rounds=int(payload.get("max_rounds", 3)),
                    max_total_sources=int(payload.get("max_total_sources", 12)),
                    max_results_per_query=int(payload.get("max_results_per_query", 3)),
                )
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path == "/api/missions/autonomous-research":
                result = self.server.service.execute_deep_research_mission(
                    str(payload.get("mission", "")),
                    run_id=payload.get("run_id"),
                    max_rounds=int(payload.get("max_rounds", 4)),
                    max_total_sources=int(payload.get("max_total_sources", 16)),
                    max_results_per_query=int(payload.get("max_results_per_query", 3)),
                )
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path == "/api/missions/demo":
                result = self.server.service.run_demo()
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path == "/api/missions":
                result = self.server.service.execute_evidence_mission(
                    str(payload.get("mission", "")),
                    payload.get("evidence", ()),
                    run_id=payload.get("run_id"),
                )
                self._json(HTTPStatus.CREATED, result.to_dict())
                return
            if path.startswith("/api/missions/") and path.endswith("/master-decision"):
                run_id = path.removeprefix("/api/missions/").removesuffix("/master-decision").rstrip("/")
                decision = self.server.service.record_master_decision(
                    run_id,
                    str(payload.get("action", "")),
                    note=str(payload.get("note", "")),
                    desired_outcome=payload.get("desired_outcome"),
                )
                self._json(HTTPStatus.CREATED, decision.__dict__)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except KeyError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found", "detail": str(exc)})
        except ProviderUnavailableError as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "provider_unavailable",
                "detail": str(exc),
            })
        except ResearchUnavailableError as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {
                "error": "research_unavailable",
                "detail": str(exc),
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "bad_request", "detail": str(exc)})
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error", "detail": type(exc).__name__})


def build_server(host: str, port: int, database: str | Path, token: str | None = None) -> MissionControlHTTPServer:
    if not _is_loopback(host) and not token:
        raise ValueError("non-loopback Mission Control requires SUPERBRAIN_MISSION_CONTROL_TOKEN")
    return MissionControlHTTPServer(
        (host, port),
        MissionControlHandler,
        MissionControlService(database),
        token,
    )


def main() -> None:
    _load_local_env()
    parser = argparse.ArgumentParser(description="SuperBrain SB-028 Mission Control")
    parser.add_argument("--host", default=os.getenv("SUPERBRAIN_MISSION_CONTROL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("SUPERBRAIN_MISSION_CONTROL_PORT", "8787")))
    parser.add_argument("--database", default=os.getenv("SUPERBRAIN_STATE_DB", "work/superbrain-state.db"))
    parser.add_argument("--open-browser", action="store_true", help="Open the exact bound Mission Control URL in the default browser")
    args = parser.parse_args()
    stealth = _stealth_enabled()
    if stealth and not _is_loopback(args.host):
        raise SystemExit("Stealth mode requires a loopback host; refusing network exposure.")
    token = os.getenv("SUPERBRAIN_MISSION_CONTROL_TOKEN")
    if stealth and not token:
        token = secrets.token_urlsafe(32)
        os.environ["SUPERBRAIN_MISSION_CONTROL_TOKEN"] = token
        try:
            token_path = Path(args.database).resolve().parent / "mission-control-access.token"
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(token + "\n", encoding="utf-8")
        except OSError:
            pass
    server = build_server(args.host, args.port, args.database, token)
    bound_port = server.server_address[1]
    url = f"http://{args.host}:{bound_port}/?build=sb027-{int(time.time())}"
    browser_url = url + (f"#access={token}" if stealth and token else "")
    try:
        marker = Path(args.database).resolve().parent / "mission-control-url.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(browser_url + "\n", encoding="utf-8")
    except OSError:
        pass
    print(f"SuperBrain Mission Control SB-028 listening on {url}", flush=True)
    if stealth:
        print("Stealth mode: loopback-only, API token required, no network discovery.", flush=True)
    if args.open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(browser_url, new=2)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
