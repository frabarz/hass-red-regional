"""Typed errors for the TransApp backend client."""

from __future__ import annotations


class TransAppError(Exception):
    """Base error for TransApp backend failures."""


class TransAppAuthError(TransAppError):
    """Backend rejected the request (stale headers or App-Version)."""


class TransAppConnectionError(TransAppError):
    """Network or server error reaching the TransApp backend."""


class TransAppRateLimitError(TransAppError):
    """Backend answered HTTP 429; caller should back off and retry later."""


class InvalidStopError(TransAppError):
    """Backend reports an unknown stop code for the zone."""
