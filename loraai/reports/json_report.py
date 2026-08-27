"""Machine-readable JSON reports.

The schema is versioned (``schema_version``) and additive: new keys may appear
in a minor release, existing keys keep their meaning. Consumers should ignore
unknown keys rather than failing.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ..models import Analysis, CleanResult, HumanizeResult
from ..sanitize import redact_secrets
from ..version import REPORT_SCHEMA_VERSION, get_version


def build(
    analysis: Analysis,
    *,
    clean: Optional[CleanResult] = None,
    humanize: Optional[HumanizeResult] = None,
    include_text: bool = False,
) -> Dict[str, Any]:
    """Assemble the report payload."""
    payload = analysis.to_dict()

    if clean is not None:
        payload["cleaning"] = clean.to_dict()
        if include_text:
            payload["cleaning"]["cleaned_text"] = clean.cleaned

    if humanize is not None:
        payload["humanization"] = humanize.to_dict()
        if include_text:
            payload["humanization"]["result_text"] = humanize.result

    return payload


def dumps(
    analysis: Analysis,
    *,
    clean: Optional[CleanResult] = None,
    humanize: Optional[HumanizeResult] = None,
    include_text: bool = False,
    indent: Optional[int] = 2,
    redact: bool = True,
) -> str:
    """Serialise the report to a JSON string."""
    payload = build(
        analysis, clean=clean, humanize=humanize, include_text=include_text
    )
    text = json.dumps(payload, indent=indent, ensure_ascii=False, sort_keys=False)
    return redact_secrets(text) if redact else text


def schema_info() -> Dict[str, str]:
    """Describe the schema, for `loraai report --schema`."""
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "loraai_version": get_version(),
        "top_level_keys": ", ".join(
            [
                "schema_version", "loraai_version", "source", "statistics",
                "style", "unicode", "ai_markers", "synthetic_signal",
                "provenance_marking", "warnings", "elapsed_ms",
                "cleaning (optional)", "humanization (optional)",
            ]
        ),
        "stability": (
            "Additive within a major version. New keys may appear; existing "
            "keys keep their meaning. Ignore unknown keys."
        ),
    }
