from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from .provider_bridge import RetrievedSource


class RetrievalPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegisteredDocument:
    source_id: str
    source_family: str
    relative_path: str
    content_type: str = "text/plain"


class LocalDocumentResolver:
    """Resolve only pre-registered UTF-8 documents below one fixed root."""

    _TYPE_BY_SUFFIX = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
    }

    def __init__(
        self,
        root: str | Path,
        documents: Sequence[RegisteredDocument],
        *,
        max_bytes: int = 1_000_000,
        clock: Callable[[], str] | None = None,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.root = Path(root).resolve()
        self.max_bytes = max_bytes
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.documents: dict[str, RegisteredDocument] = {}
        for document in documents:
            if not document.source_id:
                raise ValueError("registered source_id cannot be empty")
            if document.source_id in self.documents:
                raise ValueError(f"duplicate registered source_id: {document.source_id}")
            self.documents[document.source_id] = document

    def __call__(self, source_id: str) -> RetrievedSource | None:
        document = self.documents.get(source_id)
        if document is None:
            return None

        try:
            candidate = (self.root / document.relative_path).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RetrievalPolicyError(f"registered source is unavailable: {source_id}") from exc
        if not candidate.is_relative_to(self.root):
            raise RetrievalPolicyError(f"registered source is outside retrieval root: {source_id}")
        if not candidate.is_file():
            raise RetrievalPolicyError(f"registered source is not a file: {source_id}")

        expected_type = self._TYPE_BY_SUFFIX.get(candidate.suffix.casefold())
        if expected_type is None or document.content_type != expected_type:
            raise RetrievalPolicyError(f"registered source has an unapproved file type: {source_id}")
        if candidate.stat().st_size > self.max_bytes:
            raise RetrievalPolicyError(f"registered source exceeds size limit: {source_id}")

        with candidate.open("rb") as handle:
            payload = handle.read(self.max_bytes + 1)
        if len(payload) > self.max_bytes:
            raise RetrievalPolicyError(f"registered source exceeds size limit: {source_id}")
        try:
            content = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RetrievalPolicyError(f"registered source is not valid UTF-8: {source_id}") from exc

        return RetrievedSource(
            source_id=document.source_id,
            source_family=document.source_family,
            content=content,
            content_hash=hashlib.sha256(payload).hexdigest(),
            retrieved_at=self.clock(),
            location=candidate.relative_to(self.root).as_posix(),
            content_type=document.content_type,
        )


@dataclass(frozen=True)
class RegisteredHttpsSource:
    source_id: str
    source_family: str
    url: str
    content_type: str


@dataclass(frozen=True)
class HttpsRetrievalPolicy:
    allowed_domains: tuple[str, ...]
    allowed_ports: tuple[int, ...] = (443,)
    allowed_content_types: tuple[str, ...] = ("text/plain", "application/json")
    max_bytes: int = 1_000_000
    timeout_seconds: float = 10.0
    max_redirects: int = 3

    def __post_init__(self) -> None:
        if not self.allowed_domains:
            raise ValueError("allowed_domains cannot be empty")
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")


@dataclass(frozen=True)
class HttpsResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _resolve_public_addresses(host: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ))


def _pinned_https_get(
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
                "Accept": "text/plain, application/json",
                "Accept-Encoding": "identity",
                "Host": host if port == 443 else f"{host}:{port}",
                "User-Agent": "NEXUS-1000-evidence-retriever/0.16",
            },
        )
        response = connection.getresponse()
        headers = {name.casefold(): value for name, value in response.getheaders()}
        length = headers.get("content-length")
        if length is not None:
            try:
                if int(length) > max_bytes:
                    raise RetrievalPolicyError("remote source exceeds size limit")
            except ValueError as exc:
                raise RetrievalPolicyError("remote source has invalid content length") from exc
        body = response.read(max_bytes + 1)
        return HttpsResponse(response.status, headers, body)
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise RetrievalPolicyError("remote HTTPS retrieval failed") from exc
    finally:
        connection.close()


class HttpsSourceResolver:
    """Retrieve only registered HTTPS sources through a validated, IP-pinned connection."""

    _REDIRECTS = {301, 302, 303, 307, 308}

    def __init__(
        self,
        sources: Sequence[RegisteredHttpsSource],
        policy: HttpsRetrievalPolicy,
        *,
        dns_resolver: Callable[[str], Sequence[str]] = _resolve_public_addresses,
        transport: Callable[[str, str, float, int], HttpsResponse] = _pinned_https_get,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.policy = policy
        self.dns_resolver = dns_resolver
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())
        self.allowed_domains = {domain.casefold().rstrip(".") for domain in policy.allowed_domains}
        self.sources: dict[str, RegisteredHttpsSource] = {}
        for source in sources:
            if not source.source_id:
                raise ValueError("registered source_id cannot be empty")
            if source.source_id in self.sources:
                raise ValueError(f"duplicate registered source_id: {source.source_id}")
            self.sources[source.source_id] = source

    def _validated_target(self, url: str) -> tuple[str, str]:
        parsed = urlsplit(url)
        if parsed.scheme.casefold() != "https":
            raise RetrievalPolicyError("remote source must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise RetrievalPolicyError("remote source URL credentials are forbidden")
        host = (parsed.hostname or "").casefold().rstrip(".")
        if not host or host not in self.allowed_domains:
            raise RetrievalPolicyError("remote source domain is not on the allowlist")
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise RetrievalPolicyError("remote source has an invalid port") from exc
        if port not in self.policy.allowed_ports:
            raise RetrievalPolicyError("remote source port is not allowed")

        try:
            addresses = tuple(self.dns_resolver(host))
            parsed_addresses = tuple(ipaddress.ip_address(address) for address in addresses)
        except (OSError, ValueError) as exc:
            raise RetrievalPolicyError("remote source DNS resolution failed") from exc
        if not parsed_addresses or any(not address.is_global for address in parsed_addresses):
            raise RetrievalPolicyError("remote source must resolve only to public IP addresses")
        return host, str(parsed_addresses[0])

    def __call__(self, source_id: str) -> RetrievedSource | None:
        source = self.sources.get(source_id)
        if source is None:
            return None
        if source.content_type.casefold() not in {
            value.casefold() for value in self.policy.allowed_content_types
        }:
            raise RetrievalPolicyError("registered remote content type is not allowed")

        current_url = source.url
        redirects = 0
        while True:
            _host, pinned_ip = self._validated_target(current_url)
            response = self.transport(
                current_url,
                pinned_ip,
                self.policy.timeout_seconds,
                self.policy.max_bytes,
            )
            headers = {name.casefold(): value for name, value in response.headers.items()}
            if response.status in self._REDIRECTS:
                if redirects >= self.policy.max_redirects:
                    raise RetrievalPolicyError("remote source redirect limit exceeded")
                location = headers.get("location")
                if not location:
                    raise RetrievalPolicyError("remote source redirect has no location")
                current_url = urljoin(current_url, location)
                redirects += 1
                continue
            if response.status != 200:
                raise RetrievalPolicyError(f"remote source returned HTTP status {response.status}")

            if len(response.body) > self.policy.max_bytes:
                raise RetrievalPolicyError("remote source exceeds size limit")
            encoding = headers.get("content-encoding", "identity").casefold().strip()
            if encoding not in {"", "identity"}:
                raise RetrievalPolicyError("remote source compression is not allowed")
            raw_type = headers.get("content-type", "")
            media_type, _, parameters = raw_type.partition(";")
            media_type = media_type.casefold().strip()
            if media_type != source.content_type.casefold():
                raise RetrievalPolicyError("remote source content type does not match registration")
            if "charset=" in parameters.casefold():
                charset = parameters.casefold().split("charset=", 1)[1].split(";", 1)[0].strip(' \"')
                if charset not in {"utf-8", "utf8"}:
                    raise RetrievalPolicyError("remote source charset is not UTF-8")
            try:
                content = response.body.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise RetrievalPolicyError("remote source is not valid UTF-8") from exc
            return RetrievedSource(
                source_id=source.source_id,
                source_family=source.source_family,
                content=content,
                content_hash=hashlib.sha256(response.body).hexdigest(),
                retrieved_at=self.clock(),
                location=current_url,
                content_type=media_type,
            )
