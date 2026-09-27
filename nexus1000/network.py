from __future__ import annotations

import ipaddress
import os
import socket
import ssl
from dataclasses import dataclass
from typing import BinaryIO
from urllib.parse import urlsplit


class NetworkPolicyError(RuntimeError):
    pass


def is_tcp_port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    """Return whether a local TCP endpoint is accepting connections."""
    try:
        with socket.create_connection((host, int(port)), timeout=max(0.05, float(timeout))):
            return True
    except (OSError, ValueError):
        return False


def detect_local_tor_proxy() -> tuple[str, int] | None:
    """Detect the common Tor Browser / Tor daemon SOCKS endpoints."""
    for port in (9150, 9050):
        if is_tcp_port_open("127.0.0.1", port):
            return "127.0.0.1", port
    return None


def parse_proxy_url(value: str) -> tuple[str, str, int] | None:
    """Parse a standard HTTP(S)/SOCKS proxy URL without exposing credentials."""
    raw = value.strip()
    if not raw:
        return None
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    scheme = (parsed.scheme or "").casefold()
    aliases = {"https": "http_proxy", "http": "http_proxy", "socks": "socks5", "socks5": "socks5", "socks5h": "socks5"}
    mode = aliases.get(scheme)
    host = parsed.hostname
    port = parsed.port
    if mode is None or not host or port is None or not (1 <= int(port) <= 65535):
        return None
    return mode, host, int(port)


@dataclass(frozen=True)
class EgressConfig:
    """Application-level egress routing.

    DIRECT uses the normal network stack. HTTP_PROXY and SOCKS5 route application
    traffic through an explicit local/company proxy. TOR is a SOCKS5 mode with
    remote DNS semantics and optional .onion allowlisting.
    """
    mode: str = "direct"
    proxy_host: str | None = None
    proxy_port: int | None = None
    onion_allowlist: tuple[str, ...] = ()
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "EgressConfig":
        requested_mode = os.getenv("SUPERBRAIN_EGRESS_MODE", "direct").strip().casefold()
        aliases = {"proxy": "http_proxy", "socks": "socks5"}
        mode = aliases.get(requested_mode, requested_mode)
        if mode not in {"direct", "http_proxy", "socks5", "tor", "auto"}:
            raise NetworkPolicyError("SUPERBRAIN_EGRESS_MODE must be direct, http_proxy, socks5, tor or auto")

        host: str | None = None
        port: int | None = None
        if mode == "auto":
            detected_tor = detect_local_tor_proxy()
            if detected_tor is not None:
                mode, host, port = "tor", detected_tor[0], detected_tor[1]
            else:
                proxy_candidate = (
                    os.getenv("SUPERBRAIN_EGRESS_PROXY", "").strip()
                    or os.getenv("ALL_PROXY", "").strip()
                    or os.getenv("HTTPS_PROXY", "").strip()
                )
                parsed_proxy = parse_proxy_url(proxy_candidate)
                if parsed_proxy is not None:
                    mode, host, port = parsed_proxy
                else:
                    mode = "direct"

        if mode in {"http_proxy", "socks5", "tor"} and host is None:
            raw = os.getenv("SUPERBRAIN_EGRESS_PROXY", "").strip()
            if raw:
                parsed_proxy = parse_proxy_url(raw)
                if parsed_proxy is None:
                    raise NetworkPolicyError("SUPERBRAIN_EGRESS_PROXY must include a supported proxy scheme and port")
                parsed_mode, parsed_host, parsed_port = parsed_proxy
                # An explicit TOR mode remains TOR even if EGRESS_PROXY is present;
                # its endpoint is still treated as a SOCKS5/Tor endpoint.
                if requested_mode != "tor":
                    mode = parsed_mode
                host, port = parsed_host, parsed_port

        if host is None:
            host = os.getenv("SUPERBRAIN_PROXY_HOST", "127.0.0.1").strip()
        if port is None:
            default_port = 9150 if mode == "tor" else 1080 if mode == "socks5" else 8080
            raw_port = os.getenv("SUPERBRAIN_PROXY_PORT", "").strip()
            try:
                port = int(raw_port) if raw_port else default_port
            except ValueError as exc:
                raise NetworkPolicyError("SUPERBRAIN_PROXY_PORT must be an integer") from exc

        allowlist = tuple(
            item.strip().casefold().rstrip(".")
            for item in os.getenv("SUPERBRAIN_ONION_ALLOWLIST", "").split(",")
            if item.strip()
        )
        timeout = float(os.getenv("SUPERBRAIN_EGRESS_TIMEOUT_SECONDS", "10"))
        if timeout <= 0 or timeout > 60:
            raise NetworkPolicyError("SUPERBRAIN_EGRESS_TIMEOUT_SECONDS must be between 0 and 60")
        if mode in {"http_proxy", "socks5", "tor"} and (not host or not (1 <= int(port) <= 65535)):
            raise NetworkPolicyError("proxy host and port are required for the selected egress mode")
        return cls(mode=mode, proxy_host=host, proxy_port=int(port), onion_allowlist=allowlist, timeout_seconds=timeout)

    @property
    def privacy_enabled(self) -> bool:
        return self.mode != "direct"

    @property
    def tor_enabled(self) -> bool:
        return self.mode == "tor"

    def allows_onion(self, hostname: str) -> bool:
        host = hostname.casefold().rstrip(".")
        if not self.tor_enabled or not host.endswith(".onion"):
            return False
        return any(host == item or host.endswith("." + item) for item in self.onion_allowlist)


def validate_public_or_onion_target(hostname: str, egress: EgressConfig) -> None:
    host = hostname.casefold().rstrip(".")
    if not host:
        raise NetworkPolicyError("destination hostname is required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise NetworkPolicyError("private or local IP destinations are blocked")
        return
    if host.endswith(".onion"):
        if not egress.allows_onion(host):
            raise NetworkPolicyError(".onion destination requires Tor mode and an explicit allowlist")
        return
    blocked_suffixes = (".local", ".localhost", ".internal", ".lan")
    if host == "localhost" or host.endswith(blocked_suffixes):
        raise NetworkPolicyError("local destination hostname is blocked")


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise NetworkPolicyError("proxy closed the connection during SOCKS negotiation")
        chunks.extend(part)
    return bytes(chunks)


def _socks5_connect(proxy_host: str, proxy_port: int, target_host: str, target_port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        sock.sendall(b"\x05\x01\x00")
        if _recv_exact(sock, 2) != b"\x05\x00":
            raise NetworkPolicyError("SOCKS5 proxy does not allow unauthenticated connections")
        host_bytes = target_host.encode("idna")
        if len(host_bytes) > 255:
            raise NetworkPolicyError("destination hostname is too long")
        request = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + int(target_port).to_bytes(2, "big")
        sock.sendall(request)
        header = _recv_exact(sock, 4)
        if header[1] != 0:
            raise NetworkPolicyError(f"SOCKS5 proxy rejected connection with code {header[1]}")
        atyp = header[3]
        if atyp == 1:
            _recv_exact(sock, 4)
        elif atyp == 3:
            length = _recv_exact(sock, 1)[0]
            _recv_exact(sock, length)
        elif atyp == 4:
            _recv_exact(sock, 16)
        else:
            raise NetworkPolicyError("SOCKS5 proxy returned an invalid address type")
        _recv_exact(sock, 2)
        return sock
    except Exception:
        sock.close()
        raise


def _http_connect(proxy_host: str, proxy_port: int, target_host: str, target_port: int, timeout: float) -> socket.socket:
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        request = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            f"Connection: keep-alive\r\n\r\n"
        ).encode("ascii", errors="strict")
        sock.sendall(request)
        data = bytearray()
        while b"\r\n\r\n" not in data and len(data) < 16_384:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data.extend(chunk)
        first = bytes(data).split(b"\r\n", 1)[0]
        parts = first.split()
        if len(parts) < 2 or parts[1] != b"200":
            raise NetworkPolicyError("HTTP proxy refused CONNECT")
        return sock
    except Exception:
        sock.close()
        raise


def connect(egress: EgressConfig, target_host: str, target_port: int, *, use_remote_dns: bool = False) -> socket.socket:
    validate_public_or_onion_target(target_host, egress)
    if egress.mode == "direct":
        return socket.create_connection((target_host, target_port), timeout=egress.timeout_seconds)
    if not egress.proxy_host or not egress.proxy_port:
        raise NetworkPolicyError("proxy configuration is incomplete")
    if egress.mode == "http_proxy":
        return _http_connect(egress.proxy_host, egress.proxy_port, target_host, target_port, egress.timeout_seconds)
    # SOCKS5/Tor deliberately sends the hostname to the proxy to avoid local DNS.
    return _socks5_connect(egress.proxy_host, egress.proxy_port, target_host, target_port, egress.timeout_seconds)


def wrap_tls(sock: socket.socket, hostname: str) -> ssl.SSLSocket:
    context = ssl.create_default_context()
    return context.wrap_socket(sock, server_hostname=hostname)
