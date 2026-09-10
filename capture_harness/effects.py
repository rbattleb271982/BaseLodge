"""Capture-only side-effect guards.

Importing this module has no effect.  The server runner opts in by installing
the context manager, which restores every monkeypatch on exit.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import socket
import ipaddress
from typing import Iterator


class OutboundNetworkBlocked(RuntimeError):
    """Raised when capture code attempts an outbound network operation."""


@dataclass(frozen=True)
class NetworkAttempt:
    operation: str
    address: object


class NetworkRecorder:
    def __init__(self) -> None:
        self.attempts: list[NetworkAttempt] = []

    def record(self, operation: str, address: object) -> None:
        self.attempts.append(NetworkAttempt(operation, address))


@contextmanager
def install_capture_effects(
    recorder: NetworkRecorder | None = None,
) -> Iterator[NetworkRecorder]:
    """Install a strict outbound socket guard for the duration of a capture."""
    recorder = recorder or NetworkRecorder()
    original_create = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto

    def _is_loopback(address) -> bool:
        if isinstance(address, str):
            return True  # Unix-domain socket.
        if not isinstance(address, tuple) or not address:
            return False
        host = str(address[0]).strip("[]")
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def blocked_create(address, *args, **kwargs):
        if _is_loopback(address):
            return original_create(address, *args, **kwargs)
        recorder.record("create_connection", address)
        raise OutboundNetworkBlocked(f"Outbound network blocked: {address!r}")

    def blocked_connect(sock, address):
        if _is_loopback(address):
            return original_connect(sock, address)
        recorder.record("connect", address)
        raise OutboundNetworkBlocked(f"Outbound network blocked: {address!r}")

    def blocked_connect_ex(sock, address):
        if _is_loopback(address):
            return original_connect_ex(sock, address)
        recorder.record("connect_ex", address)
        raise OutboundNetworkBlocked(f"Outbound network blocked: {address!r}")

    def blocked_sendto(sock, data, *args):
        address = args[-1] if args and not isinstance(args[-1], int) else None
        recorder.record("sendto", address)
        raise OutboundNetworkBlocked(f"Outbound network blocked: {address!r}")

    socket.create_connection = blocked_create
    socket.socket.connect = blocked_connect
    socket.socket.connect_ex = blocked_connect_ex
    socket.socket.sendto = blocked_sendto
    try:
        yield recorder
    finally:
        socket.create_connection = original_create
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex
        socket.socket.sendto = original_sendto


# Descriptive alias for runners that prefer the guard terminology.
install_network_guard = install_capture_effects