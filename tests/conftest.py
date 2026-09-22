"""Global test safety controls."""

from __future__ import annotations

import socket

import pytest


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every test fail immediately if application code attempts network I/O."""

    def denied(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("network access is forbidden during tests")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
