"""Error types for the UniFi Access adapter layer."""

from __future__ import annotations


class UnifiAccessBridgeError(Exception):
    """Base adapter error."""


class UnifiAccessAuthenticationError(UnifiAccessBridgeError):
    """Raised when the Access controller rejects credentials."""


class UnifiAccessCannotConnectError(UnifiAccessBridgeError):
    """Raised when the Access controller cannot be reached."""


class UnifiAccessSSLError(UnifiAccessBridgeError):
    """Raised when SSL verification fails."""


class UnifiAccessDependencyError(UnifiAccessBridgeError):
    """Raised when the upstream client dependency is unavailable."""
