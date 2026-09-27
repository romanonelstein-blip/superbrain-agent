from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import ssl
import http.client
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, Iterable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .models import Evidence, Stance
from .network import EgressConfig, NetworkPolicyError, connect, wrap_tls, validate_public_or_onion_target
from .source_retrieval import HttpsResponse, RetrievalPolicyError, _PinnedHTTPSConnection


MAX_QUERY_CHARS = 500
MAX_RESULTS_PER_QUERY = 5
MAX_RESEARCH_SOURCES = 8
MAX_SEARCH_RESPONSE_BYTES = 2_000_000
MAX_SOURCE_BYTES = 750_000


class ResearchUnavailableError(RuntimeError):
    """Raised when no configured web-search backend can execute research."""


class ResearchPolicyError(RuntimeError):
    """Raised when a search result or retrieved page violates research policy."""


@dataclass(frozen=True)
class ResearchQuery:
    query: str
    stance: Stance
    purpose: str


@dataclass(frozen=True)
class ResearchPlan:
    mission: str
    queries: tuple[ResearchQuery, ...]
    max_results_per_query: int = 3
    max_sources: int = 6

    def to_dict(self) -> dict:
        payload = asdict(self)
        for item, original in zip(payload["queries"], self.queries):
            item["stance"] = original.stance.value
        return payload


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    provider: str
    rank: int
    query: str
    stance: Stance
    score: float | None = None


@dataclass(frozen=True)
class RetrievedResearchSource:
    source_id: str
    source_family: str
    title: str
    url: str
    excerpt: str
    content_hash: str
    retrieved_at: str
    content_type: str
    query: str
    stance: Stance
    search_provider: str
    rank: int

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["stance"] = self.stance.value
        return payload


@dataclass(frozen=True)
class ResearchOutcome:
    plan: ResearchPlan
    search_provider: str
    sources: tuple[RetrievedResearchSource, ...]
    evidence: tuple[Evidence, ...]
    skipped_results: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "plan": self.plan.to_dict(),
            "search_provider": self.search_provider,
            "sources": [source.to_dict() for source in self.sources],
            "evidence_count": len(self.evidence),
            "skipped_results": list(self.skipped_results),
        }


class WebSearchClient(Protocol):
    name: str

    def search(self, query: str, limit: int) -> Sequence[SearchHit]: ...


class SourceFetcher(Protocol):
    def fetch(self, hit: SearchHit) -> RetrievedResearchSource: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_query(value: str) -> str:
    value = " ".join(value.split())
    if len(value) <= MAX_QUERY_CHARS:
        return value
    return value[: MAX_QUERY_CHARS - 1].rstrip() + "…"


def build_research_plan(
    mission: str,
    *,
    max_results_per_query: int = 3,
    max_sources: int = 6,
) -> ResearchPlan:
    mission = " ".join(mission.split()).strip()
    if not mission:
        raise ValueError("mission cannot be empty")
    if not 1 <= max_results_per_query <= MAX_RESULTS_PER_QUERY:
        raise ValueError(f"max_results_per_query must be between 1 and {MAX_RESULTS_PER_QUERY}")
    if not 1 <= max_sources <= MAX_RESEARCH_SOURCES:
        raise ValueError(f"max_sources must be between 1 and {MAX_RESEARCH_SOURCES}")

    base = _bounded_query(mission)
    challenge = _bounded_query(f"{mission} risks criticism counterevidence limitations")
    return ResearchPlan(
        mission=mission,
        queries=(
            ResearchQuery(base, Stance.SUPPORT, "primary evidence"),
            ResearchQuery(challenge, Stance.CHALLENGE, "counter-evidence and limitations"),
        ),
        max_results_per_query=max_results_per_query,
        max_sources=max_sources,
    )


class _SearchHTMLParser(HTMLParser):
    """Small dependency-free parser for DuckDuckGo HTML result pages."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str, str]] = []
        self._url: str | None = None
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_dict = dict(attrs)
        classes = set((attrs_dict.get("class") or "").split())
        if tag == "a" and "result__a" in classes:
            self._url = attrs_dict.get("href")
            self._title = []
            self._snippet = []
            self._in_title = True
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
        if self._in_snippet:
            self._in_snippet = False
            if self._url:
                self.results.append((
                    " ".join("".join(self._title).split()),
                    self._url,
                    " ".join("".join(self._snippet).split()),
                ))
                self._url = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        elif self._in_snippet:
            self._snippet.append(data)


def _read_https_bytes(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    egress: EgressConfig,
    headers: Mapping[str, str],
) -> tuple[int, Mapping[str, str], bytes]:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() != "https":
        raise ResearchUnavailableError("research network requests must use HTTPS")
    host = parsed.hostname or ""
    port = parsed.port or 443
    try:
        validate_public_or_onion_target(host, egress)
    except NetworkPolicyError as exc:
        raise ResearchUnavailableError(str(exc)) from exc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    if egress.mode == "direct":
        # Do not inherit ambient HTTP(S)_PROXY/ALL_PROXY settings in explicit DIRECT
        # mode. Resolve the public hostname ourselves, pin the connection to each
        # resolved address, and keep TLS SNI bound to the original hostname.
        try:
            addresses = tuple(_resolve_public_addresses(host))
        except Exception as exc:
            raise ResearchUnavailableError("research network request failed: DNS resolution unavailable") from exc
        last_error: Exception | None = None
        for pinned_ip in addresses:
            try:
                response = _pinned_research_get(url, pinned_ip, timeout, max_bytes)
                return response.status, response.headers, response.body
            except (OSError, ssl.SSLError, http.client.HTTPException, RetrievalPolicyError) as exc:
                last_error = exc
                continue
        raise ResearchUnavailableError("research network request failed: no resolved address accepted the connection") from last_error
    raw_sock = None
    tls = None
    try:
        raw_sock = connect(egress, host, port)
        tls = wrap_tls(raw_sock, host)
        req_headers = dict(headers)
        req_headers.setdefault("Host", host if port == 443 else f"{host}:{port}")
        req_headers.setdefault("Connection", "close")
        payload = (f"GET {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in req_headers.items()) + "\r\n").encode("utf-8")
        tls.sendall(payload)
        response = http.client.HTTPResponse(tls)
        response.begin()
        return response.status, {k.casefold(): v for k, v in response.getheaders()}, response.read(max_bytes + 1)
    except (OSError, ssl.SSLError, http.client.HTTPException, NetworkPolicyError) as exc:
        raise ResearchUnavailableError("research network request failed") from exc
    finally:
        try:
            if tls is not None:
                tls.close()
            elif raw_sock is not None:
                raw_sock.close()
        except Exception:
            pass


def _read_json_response(request: Request, *, timeout: float, egress: EgressConfig | None = None) -> Mapping[str, object]:
    egress = egress or EgressConfig.from_env()
    url = request.full_url
    headers = {str(k): str(v) for k, v in request.header_items()}
    if request.data is not None:
        # Tavily currently uses a JSON POST. Keep its existing direct path unless the
        # caller supplies an explicit HTTPS proxy environment at the process level.
        if egress.mode != "direct":
            raise ResearchUnavailableError("Tavily POST is not available through the selected application egress mode")
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read(MAX_SEARCH_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise ResearchUnavailableError(f"web search returned HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ResearchUnavailableError("web search request failed") from exc
    else:
        status, _response_headers, raw = _read_https_bytes(
            url, timeout=timeout, max_bytes=MAX_SEARCH_RESPONSE_BYTES, egress=egress, headers=headers
        )
        if status >= 400:
            raise ResearchUnavailableError(f"web search returned HTTP {status}")
    if len(raw) > MAX_SEARCH_RESPONSE_BYTES:
        raise ResearchUnavailableError("web search response exceeded the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchUnavailableError("web search returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ResearchUnavailableError("web search returned an invalid payload")
    return payload


class TavilySearchClient:
    name = "tavily"

    def __init__(self, api_key: str, *, timeout_seconds: float = 10.0, egress: EgressConfig | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Tavily API key cannot be empty")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.egress = egress or EgressConfig.from_env()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        limit = max(1, min(MAX_RESULTS_PER_QUERY, int(limit)))
        body = json.dumps({
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": limit,
            "include_answer": False,
            "include_raw_content": False,
        }).encode("utf-8")
        request = Request(
            "https://api.tavily.com/search",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        payload = _read_json_response(request, timeout=self.timeout_seconds, egress=self.egress)
        rows = payload.get("results", [])
        if not isinstance(rows, list):
            raise ResearchUnavailableError("Tavily response has no result list")
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, dict):
                continue
            url = str(row.get("url", "")).strip()
            if not url:
                continue
            score = row.get("score")
            hits.append(SearchHit(
                title=str(row.get("title", "")).strip() or url,
                url=url,
                snippet=str(row.get("content", "")).strip(),
                provider=self.name,
                rank=rank,
                query=query,
                stance=Stance.NEUTRAL,
                score=float(score) if isinstance(score, (int, float)) else None,
            ))
        return tuple(hits)


class BraveSearchClient:
    name = "brave"

    def __init__(self, api_key: str, *, timeout_seconds: float = 10.0, egress: EgressConfig | None = None) -> None:
        if not api_key.strip():
            raise ValueError("Brave Search API key cannot be empty")
        self.api_key = api_key.strip()
        self.timeout_seconds = timeout_seconds
        self.egress = egress or EgressConfig.from_env()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        limit = max(1, min(MAX_RESULTS_PER_QUERY, int(limit)))
        url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({
            "q": query,
            "count": limit,
            "safesearch": "moderate",
        })
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
                "User-Agent": "SuperBrain-Research/0.23",
            },
            method="GET",
        )
        payload = _read_json_response(request, timeout=self.timeout_seconds, egress=self.egress)
        web = payload.get("web", {})
        rows = web.get("results", []) if isinstance(web, dict) else []
        if not isinstance(rows, list):
            raise ResearchUnavailableError("Brave response has no result list")
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, dict):
                continue
            target = str(row.get("url", "")).strip()
            if not target:
                continue
            hits.append(SearchHit(
                title=str(row.get("title", "")).strip() or target,
                url=target,
                snippet=str(row.get("description", "")).strip(),
                provider=self.name,
                rank=rank,
                query=query,
                stance=Stance.NEUTRAL,
            ))
        return tuple(hits)


class GitHubSearchClient:
    name = "github"

    def __init__(self, token: str = "", *, timeout_seconds: float = 10.0, egress: EgressConfig | None = None) -> None:
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        self.egress = egress or EgressConfig.from_env()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        limit = max(1, min(MAX_RESULTS_PER_QUERY, int(limit)))
        url = "https://api.github.com/search/repositories?" + urlencode({"q": query, "per_page": limit, "sort": "updated", "order": "desc"})
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SuperBrain-OSINT/0.26",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        status, _response_headers, raw = _read_https_bytes(url, timeout=self.timeout_seconds, max_bytes=MAX_SEARCH_RESPONSE_BYTES, egress=self.egress, headers=headers)
        if status == 403:
            raise ResearchUnavailableError("GitHub search rate limit or access policy blocked the request")
        if status >= 400:
            raise ResearchUnavailableError(f"GitHub search returned HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResearchUnavailableError("GitHub search returned invalid JSON") from exc
        rows = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            raise ResearchUnavailableError("GitHub search returned no result list")
        hits: list[SearchHit] = []
        for rank, row in enumerate(rows[:limit], start=1):
            if not isinstance(row, dict):
                continue
            target = str(row.get("html_url", "")).strip()
            if not target:
                continue
            description = str(row.get("description", "")).strip()
            updated = str(row.get("updated_at", "")).strip()
            snippet = " — ".join(part for part in (description, f"updated {updated}" if updated else "") if part)
            hits.append(SearchHit(
                title=str(row.get("full_name", "GitHub repository")),
                url=target,
                snippet=snippet,
                provider=self.name,
                rank=rank,
                query=query,
                stance=Stance.NEUTRAL,
            ))
        return tuple(hits)


class DuckDuckGoSearchClient:
    name = "duckduckgo"

    def __init__(self, *, timeout_seconds: float = 10.0, egress: EgressConfig | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.egress = egress or EgressConfig.from_env()

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        limit = max(1, min(MAX_RESULTS_PER_QUERY, int(limit)))
        url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
        status, _headers, raw = _read_https_bytes(url, timeout=self.timeout_seconds, max_bytes=MAX_SEARCH_RESPONSE_BYTES, egress=self.egress, headers={"Accept": "text/html", "User-Agent": "SuperBrain-OSINT/0.26"})
        if status >= 400:
            raise ResearchUnavailableError(f"DuckDuckGo search returned HTTP {status}")
        parser = _SearchHTMLParser()
        parser.feed(raw.decode("utf-8", errors="strict"))
        from urllib.parse import parse_qs
        hits: list[SearchHit] = []
        for rank, (title, raw_url, snippet) in enumerate(parser.results[:limit], start=1):
            target = raw_url
            if raw_url.startswith("//"):
                target = "https:" + raw_url
            parsed = urlsplit(target)
            if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                decoded = parse_qs(parsed.query).get("uddg", [])
                if decoded:
                    target = decoded[0]
            hits.append(SearchHit(title=title or target, url=target, snippet=snippet, provider=self.name, rank=rank, query=query, stance=Stance.NEUTRAL))
        return tuple(hits)


class CompositeSearchClient:
    name = "composite"

    def __init__(self, clients: Sequence[WebSearchClient]) -> None:
        self.clients = tuple(clients)
        if not self.clients:
            raise ValueError("at least one search client is required")
        self.name = "+".join(client.name for client in self.clients)

    def search(self, query: str, limit: int) -> Sequence[SearchHit]:
        hits: list[SearchHit] = []
        failures: list[str] = []
        for client in self.clients:
            try:
                hits.extend(client.search(query, max(1, min(MAX_RESULTS_PER_QUERY, limit))))
            except ResearchUnavailableError as exc:
                failures.append(f"{client.name}:{type(exc).__name__}")
        if not hits and failures:
            raise ResearchUnavailableError("all configured research providers failed")
        output: list[SearchHit] = []
        seen: set[str] = set()
        for hit in hits:
            key = hit.url.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            output.append(hit)
            if len(output) >= limit:
                break
        return tuple(output)


def search_client_from_env() -> WebSearchClient:
    egress = EgressConfig.from_env()
    sources = [item.strip().casefold() for item in os.getenv("SUPERBRAIN_RESEARCH_SOURCES", "web,github,duckduckgo").split(",") if item.strip()]
    preferred = os.getenv("SUPERBRAIN_WEB_SEARCH_PROVIDER", "").strip().casefold()
    if preferred and preferred not in {"tavily", "brave"}:
        raise ResearchUnavailableError("SUPERBRAIN_WEB_SEARCH_PROVIDER must be 'tavily' or 'brave'")
    tavily = os.getenv("TAVILY_API_KEY", "").strip()
    brave = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    github = os.getenv("GITHUB_TOKEN", "").strip()
    clients: list[WebSearchClient] = []
    for source in sources:
        if source == "web":
            chosen = preferred or ("tavily" if tavily else "brave" if brave else "")
            if chosen == "tavily" and tavily:
                clients.append(TavilySearchClient(tavily, egress=egress))
            elif chosen == "brave" and brave:
                clients.append(BraveSearchClient(brave, egress=egress))
        elif source == "tavily" and tavily:
            clients.append(TavilySearchClient(tavily, egress=egress))
        elif source == "brave" and brave:
            clients.append(BraveSearchClient(brave, egress=egress))
        elif source == "github":
            clients.append(GitHubSearchClient(github, egress=egress))
        elif source in {"duckduckgo", "ddg"}:
            clients.append(DuckDuckGoSearchClient(egress=egress))
    if not clients:
        raise ResearchUnavailableError("No research backend is configured")
    return CompositeSearchClient(clients)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


def _normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    host = (parsed.hostname or "").casefold().rstrip(".")
    if scheme != "https" or not host:
        raise ResearchPolicyError("research sources must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ResearchPolicyError("research source URL credentials are forbidden")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ResearchPolicyError("research source URLs may not use IP literals")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ResearchPolicyError("research source URL has an invalid port") from exc
    if port != 443:
        raise ResearchPolicyError("research source URL must use port 443")
    netloc = host
    if parsed.port and parsed.port != 443:
        netloc = f"{host}:{parsed.port}"
    return urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))




def _pinned_research_get(
    url: str,
    pinned_ip: str,
    timeout_seconds: float,
    max_bytes: int,
) -> HttpsResponse:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    connection = _PinnedHTTPSConnection(host, pinned_ip, port, timeout_seconds)
    try:
        connection.request(
            "GET",
            path,
            headers={
                "Accept": "text/html, text/plain;q=0.9, application/json;q=0.8",
                "Accept-Encoding": "identity",
                "Host": host if port == 443 else f"{host}:{port}",
                "User-Agent": "SuperBrain-Research/0.23",
            },
        )
        response = connection.getresponse()
        headers = {name.casefold(): value for name, value in response.getheaders()}
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) > max_bytes:
                    raise ResearchPolicyError("research source exceeded the size limit")
            except ValueError as exc:
                raise ResearchPolicyError("research source has invalid content length") from exc
        body = response.read(max_bytes + 1)
        return HttpsResponse(response.status, headers, body)
    except ResearchPolicyError:
        raise
    except Exception as exc:
        raise ResearchPolicyError("research HTTPS retrieval failed") from exc
    finally:
        connection.close()


def _resolve_public_addresses(host: str) -> tuple[str, ...]:
    try:
        addresses = tuple(dict.fromkeys(
            result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ))
        parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    except (OSError, ValueError) as exc:
        raise ResearchPolicyError("research source DNS resolution failed") from exc
    if not parsed or any(not address.is_global for address in parsed):
        raise ResearchPolicyError("research source must resolve only to public IP addresses")
    return tuple(str(address) for address in parsed)


def _same_redirect_host(original: str, redirected: str) -> bool:
    a = (urlsplit(original).hostname or "").casefold().rstrip(".")
    b = (urlsplit(redirected).hostname or "").casefold().rstrip(".")
    if a == b:
        return True
    if a.startswith("www.") and a[4:] == b:
        return True
    if b.startswith("www.") and b[4:] == a:
        return True
    return False


class SafeResearchSourceFetcher:
    """Fetch a search-discovered public HTTPS page with strict SSRF and size guards."""

    _REDIRECTS = {301, 302, 303, 307, 308}
    _ALLOWED_TYPES = {"text/html", "text/plain", "application/json"}

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = MAX_SOURCE_BYTES,
        max_redirects: int = 2,
        transport: Callable[[str, str, float, int], HttpsResponse] = _pinned_research_get,
        dns_resolver: Callable[[str], Sequence[str]] | None = None,
        clock: Callable[[], str] = _utc_now,
        egress: EgressConfig | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.transport = transport
        self.dns_resolver = dns_resolver or _resolve_public_addresses
        self.clock = clock
        self.egress = egress or EgressConfig.from_env()

    def _validated_target(self, url: str) -> tuple[str, str]:
        normalized = _normalize_url(url)
        host = urlsplit(normalized).hostname or ""
        if self.egress.mode == "tor" and host.casefold().endswith(".onion"):
            if not self.egress.allows_onion(host):
                raise ResearchPolicyError(".onion destination requires explicit Tor allowlist")
            return normalized, host
        if self.egress.mode != "direct":
            try:
                validate_public_or_onion_target(host, self.egress)
            except NetworkPolicyError as exc:
                raise ResearchPolicyError(str(exc)) from exc
            return normalized, host
        try:
            addresses = tuple(self.dns_resolver(host))
            parsed = tuple(ipaddress.ip_address(value) for value in addresses)
        except (OSError, ValueError) as exc:
            raise ResearchPolicyError("research source DNS resolution failed") from exc
        if not parsed or any(not address.is_global for address in parsed):
            raise ResearchPolicyError("research source must resolve only to public IP addresses")
        return normalized, str(parsed[0])

    def fetch(self, hit: SearchHit) -> RetrievedResearchSource:
        current, pinned_ip = self._validated_target(hit.url)
        original = current
        redirects = 0
        while True:
            if self.egress.mode == "direct":
                response = self.transport(current, pinned_ip, self.timeout_seconds, self.max_bytes)
            else:
                status, headers, body = _read_https_bytes(current, timeout=self.timeout_seconds, max_bytes=self.max_bytes, egress=self.egress, headers={"Accept": "text/html, text/plain, application/json", "Accept-Encoding": "identity", "User-Agent": "SuperBrain-Research/0.26"})
                response = HttpsResponse(status, headers, body)
            headers = {str(k).casefold(): str(v) for k, v in response.headers.items()}
            if response.status in self._REDIRECTS:
                if redirects >= self.max_redirects:
                    raise ResearchPolicyError("research source redirect limit exceeded")
                location = headers.get("location")
                if not location:
                    raise ResearchPolicyError("research source redirect has no location")
                redirected = _normalize_url(urljoin(current, location))
                if not _same_redirect_host(original, redirected):
                    raise ResearchPolicyError("research source redirected to a different host")
                current, pinned_ip = self._validated_target(redirected)
                redirects += 1
                continue
            if response.status != 200:
                raise ResearchPolicyError(f"research source returned HTTP status {response.status}")
            if len(response.body) > self.max_bytes:
                raise ResearchPolicyError("research source exceeded the size limit")
            encoding = headers.get("content-encoding", "identity").casefold().strip()
            if encoding not in {"", "identity"}:
                raise ResearchPolicyError("compressed research responses are not accepted")
            raw_type = headers.get("content-type", "")
            media_type, _, params = raw_type.partition(";")
            media_type = media_type.casefold().strip()
            if media_type not in self._ALLOWED_TYPES:
                raise ResearchPolicyError("research source content type is not supported")
            if "charset=" in params.casefold():
                charset = params.casefold().split("charset=", 1)[1].split(";", 1)[0].strip(' \"')
                if charset not in {"utf-8", "utf8"}:
                    raise ResearchPolicyError("research source charset is not UTF-8")
            try:
                text = response.body.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ResearchPolicyError("research source is not valid UTF-8") from exc
            if media_type == "text/html":
                parser = _TextExtractor()
                parser.feed(text)
                text = parser.text()
            else:
                text = " ".join(text.split())
            if not text:
                raise ResearchPolicyError("research source contained no usable text")
            excerpt = text[:700].strip()
            if len(text) > 700:
                excerpt = excerpt.rstrip() + "…"
            host = (urlsplit(current).hostname or "").casefold().rstrip(".")
            source_id = "web-" + hashlib.sha256(current.encode("utf-8")).hexdigest()[:20]
            return RetrievedResearchSource(
                source_id=source_id,
                source_family=host,
                title=hit.title,
                url=current,
                excerpt=excerpt,
                content_hash=hashlib.sha256(response.body).hexdigest(),
                retrieved_at=self.clock(),
                content_type=media_type,
                query=hit.query,
                stance=hit.stance,
                search_provider=hit.provider,
                rank=hit.rank,
            )


def _dedupe_hits(hits: Iterable[SearchHit]) -> tuple[SearchHit, ...]:
    seen: set[str] = set()
    output: list[SearchHit] = []
    for hit in hits:
        try:
            normalized = _normalize_url(hit.url)
        except ResearchPolicyError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(hit)
    return tuple(output)


class ResearchEngine:
    def __init__(
        self,
        search_client: WebSearchClient,
        *,
        source_fetcher: SourceFetcher | None = None,
    ) -> None:
        self.search_client = search_client
        self.source_fetcher = source_fetcher or SafeResearchSourceFetcher(egress=EgressConfig.from_env())

    def run(self, plan: ResearchPlan) -> ResearchOutcome:
        hits: list[SearchHit] = []
        skipped: list[str] = []
        egress = getattr(self.source_fetcher, "egress", EgressConfig.from_env())
        if egress.tor_enabled:
            onion_urls = re.findall(r"https://[a-z2-7]{56}\.onion(?:/[^\s]*)?", plan.mission, flags=re.IGNORECASE)
            for index, onion_url in enumerate(onion_urls, start=1):
                host = urlsplit(onion_url).hostname or ""
                if egress.allows_onion(host):
                    hits.append(SearchHit("Configured onion target", onion_url, "Explicitly supplied onion target", "tor-direct", index, plan.mission, Stance.NEUTRAL))
        for query in plan.queries:
            query_limit = (
                plan.max_results_per_query
                if query.stance is Stance.SUPPORT
                else max(1, plan.max_results_per_query // 2)
            )
            rows = self.search_client.search(query.query, query_limit)
            for hit in rows:
                hits.append(SearchHit(
                    title=hit.title,
                    url=hit.url,
                    snippet=hit.snippet,
                    provider=hit.provider,
                    rank=hit.rank,
                    query=query.query,
                    stance=query.stance,
                    score=hit.score,
                ))

        sources: list[RetrievedResearchSource] = []
        for hit in _dedupe_hits(hits):
            if len(sources) >= plan.max_sources:
                break
            try:
                source = self.source_fetcher.fetch(hit)
            except (ResearchPolicyError, RetrievalPolicyError, OSError) as exc:
                skipped.append(f"{hit.url}: {type(exc).__name__}")
                continue
            sources.append(source)

        evidence = tuple(Evidence(
            id=f"research:{source.source_id}",
            claim=source.excerpt,
            stance=source.stance,
            source_id=source.source_id,
            source_family=source.source_family,
            reliability=0.78 if source.stance is Stance.SUPPORT else 0.72,
            freshness=0.85,
            relevance=max(0.55, 1.0 - (source.rank - 1) * 0.10),
            verified=True,
            citation=source.excerpt,
            content_hash=source.content_hash,
            retrieved_at=source.retrieved_at,
            location=source.url,
            content_type=source.content_type,
            provider=f"web-search:{source.search_provider}",
            provider_model=None,
            provider_request_id=source.query,
            provider_agent="research",
            provider_attempts=1,
            provider_latency_ms=None,
        ) for source in sources)

        return ResearchOutcome(
            plan=plan,
            search_provider=self.search_client.name,
            sources=tuple(sources),
            evidence=evidence,
            skipped_results=tuple(skipped),
        )


def configured_search_providers() -> tuple[str, ...]:
    values: list[str] = []
    if os.getenv("TAVILY_API_KEY", "").strip():
        values.append("tavily")
    if os.getenv("BRAVE_SEARCH_API_KEY", "").strip():
        values.append("brave")
    sources = {item.strip().casefold() for item in os.getenv("SUPERBRAIN_RESEARCH_SOURCES", "web,github,duckduckgo").split(",") if item.strip()}
    if "github" in sources:
        values.append("github")
    if "duckduckgo" in sources or "ddg" in sources:
        values.append("duckduckgo")
    egress = EgressConfig.from_env()
    if egress.privacy_enabled:
        values.append(egress.mode)
    return tuple(dict.fromkeys(values))
