"""Single source of truth for the package version."""

from __future__ import annotations

__version__ = "1.0.0"

#: Schema version for machine-readable reports. Bump on breaking schema change.
REPORT_SCHEMA_VERSION = "1.0"


def get_version() -> str:
    """Return the installed version, preferring package metadata when available."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("loraai-cli")
    except Exception:  # pragma: no cover - metadata missing in source checkouts
        return __version__
