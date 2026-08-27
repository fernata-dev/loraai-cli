"""Exception hierarchy for loraai.

Every error raised through normal user interaction derives from :class:`LoraError`
so the CLI can print a clean message instead of a traceback.
"""

from __future__ import annotations


class LoraError(Exception):
    """Base class for all expected, user-facing failures."""

    #: Process exit code associated with this failure class.
    exit_code = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class InputError(LoraError):
    """Raised when the caller supplied no input, or contradictory input."""

    exit_code = 2


class FileAccessError(InputError):
    """Raised when a path is missing, unreadable, or outside allowed bounds."""

    exit_code = 2


class BinaryFileError(InputError):
    """Raised when a file does not decode as text under any candidate encoding."""

    exit_code = 2


class FileTooLargeError(InputError):
    """Raised when an input exceeds the configured size ceiling."""

    exit_code = 2


class ConfigError(LoraError):
    """Raised when the configuration file is malformed or has invalid values."""

    exit_code = 3


class ProviderError(LoraError):
    """Raised when an external rewrite provider is unavailable or misconfigured."""

    exit_code = 4


class ProviderNotConfigured(ProviderError):
    """Raised when a provider was requested but has no credentials configured."""

    exit_code = 4
