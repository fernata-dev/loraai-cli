"""Environment diagnostics.

`loraai doctor` actually exercises things rather than asserting them: it runs
the analysis engine against a sample with known-planted markers and checks
that they come back. A green doctor means the engine works here, not merely
that the imports resolved.
"""

from __future__ import annotations

import locale
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Dict, List

from rich import box
from rich.console import Group
from rich.table import Table
from rich.text import Text

from ..config import Config, config_dir
from ..version import get_version
from . import render as ui

#: Lowest Python the dependency set supports (click requires 3.10).
MIN_PYTHON = (3, 10)


@dataclass
class Check:
    """One diagnostic result."""

    name: str
    ok: bool
    detail: str
    required: bool = True
    remedy: str = ""

    @property
    def status(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.required else "SKIP"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "ok": self.ok,
            "required": self.required,
            "detail": self.detail,
            "remedy": self.remedy,
        }


def _check_python() -> Check:
    version = sys.version_info
    ok = version[:2] >= MIN_PYTHON
    return Check(
        "Python version",
        ok,
        f"{platform.python_version()} ({sys.executable})",
        remedy="" if ok else
        f"loraai needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
    )


def _check_package() -> Check:
    try:
        import loraai  # noqa: F401

        return Check("Package", True, f"loraai {get_version()}")
    except Exception as exc:  # pragma: no cover - only if install is broken
        return Check(
            "Package", False, str(exc), remedy="Reinstall with: pip install -e ."
        )


def _check_dependency(module: str, *, required: bool = True) -> Check:
    try:
        import importlib
        import importlib.metadata as metadata

        importlib.import_module(module)
        try:
            version = metadata.version(module)
        except Exception:
            version = "installed"
        return Check(module, True, version, required=required)
    except ImportError:
        return Check(
            module, False, "not installed", required=required,
            remedy=f"pip install {module}",
        )


def _check_entrypoint() -> Check:
    path = shutil.which("loraai")
    if path:
        return Check("CLI on PATH", True, path)
    return Check(
        "CLI on PATH", False, "loraai not found on PATH", required=False,
        remedy="Run via 'python -m loraai', or add the install directory to PATH.",
    )


def _check_unicode_output() -> Check:
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    ok = "utf" in encoding
    sample = "مرحبا · 中文 · ✓ · U+200B"
    detail = f"stdout encoding {encoding or 'unknown'} — {sample}"
    return Check(
        "Unicode output", ok, detail, required=False,
        remedy="" if ok else
        "Set PYTHONIOENCODING=utf-8 so non-ASCII output renders correctly.",
    )


def _check_locale() -> Check:
    try:
        current = locale.getlocale()
        detail = f"{current[0] or 'C'}.{current[1] or 'unset'}"
    except Exception as exc:  # pragma: no cover - platform quirk
        return Check("Locale", False, str(exc), required=False)
    return Check("Locale", True, detail, required=False)


def _check_terminal() -> Check:
    size = shutil.get_terminal_size(fallback=(80, 24))
    term = os.environ.get("TERM", "unset")
    ok = size.columns >= 60
    return Check(
        "Terminal", ok, f"{size.columns}x{size.lines}, TERM={term}", required=False,
        remedy="" if ok else "The TUI works best at 80 columns or wider.",
    )


def _check_config(config: Config) -> Check:
    directory = config_dir()
    writable = os.access(directory.parent, os.W_OK) if not directory.exists() else \
        os.access(directory, os.W_OK)
    source = config.source_path or "built-in defaults"
    return Check(
        "Configuration", True,
        f"{source}{'' if writable else '  (directory not writable)'}",
        required=False,
        remedy="" if writable else f"Cannot write to {directory}.",
    )


def _check_engine() -> Check:
    """End-to-end self-test with known-planted markers.

    The sample carries one zero-width space, one bidi override, one smuggled
    tag payload and one homoglyph. All four must be found, and the payload must
    decode to exactly the planted string.
    """
    try:
        from ..analysis.payload import encode_tags
        from ..analysis.unicode_forensics import scan
        from ..cleaning import clean

        planted = "loraai-selftest"
        sample = (
            "The quick brown fox​ jumps over the lazy dog."
            + encode_tags(planted)
            + "‮overridden‬ and pаypal here."
        )
        report = scan(sample)

        classes = set(report.class_counts)
        missing = {
            "zero-width", "bidi-override", "tag-character", "confusable",
        } - classes
        if missing:
            return Check(
                "Engine self-test", False,
                f"did not detect: {', '.join(sorted(missing))}",
                remedy="The detection tables may be corrupted; reinstall.",
            )

        decoded = [p.decoded for p in report.payloads]
        if planted not in decoded:
            return Check(
                "Engine self-test", False,
                f"payload decode failed (got {decoded!r})",
                remedy="The payload decoder is not working; reinstall.",
            )

        cleaned = clean(sample, "standard")
        if not cleaned.semantic_preserved:
            return Check(
                "Engine self-test", False,
                "cleaning altered visible content",
                remedy="The cleaning engine is not preserving semantics; reinstall.",
            )
        if "​" in cleaned.cleaned or "‮" in cleaned.cleaned:
            return Check(
                "Engine self-test", False, "cleaning left invisible characters behind",
                remedy="The cleaning engine is not removing markers; reinstall.",
            )

        return Check(
            "Engine self-test", True,
            f"4/4 marker classes detected, payload decoded, cleaning verified",
        )
    except Exception as exc:  # pragma: no cover - defensive
        return Check(
            "Engine self-test", False, f"{type(exc).__name__}: {exc}",
            remedy="Report this at the project issue tracker.",
        )


def _check_providers() -> List[Check]:
    from ..humanize.providers import available_providers

    checks = []
    for provider in available_providers():
        if provider["name"] == "ollama":
            continue  # local server; presence cannot be judged without a request
        checks.append(
            Check(
                f"Provider: {provider['name']}",
                bool(provider["configured"]),
                f"{provider['model']}"
                + ("" if provider["configured"] else f" ({provider['env_var']} unset)"),
                required=False,
                remedy="" if provider["configured"] else
                f"Set {provider['env_var']} to enable LLM-backed rewriting.",
            )
        )
    return checks


def run_checks(config: Config) -> List[Check]:
    """Run every diagnostic."""
    checks: List[Check] = [
        _check_python(),
        _check_package(),
        _check_dependency("rich"),
        _check_dependency("textual"),
        _check_dependency("click"),
        _check_entrypoint(),
        _check_unicode_output(),
        _check_locale(),
        _check_terminal(),
        _check_config(config),
        _check_engine(),
    ]
    checks.extend(_check_providers())
    return checks


def render_checks(checks: List[Check]):
    """Render the diagnostics table."""
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, header_style=f"bold {ui.MUTED}")
    table.add_column("Check", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail")

    for check in checks:
        if check.ok:
            style = ui.HUMAN
        elif check.required:
            style = ui.SYNTH
        else:
            style = ui.NEUTRAL
        table.add_row(
            check.name, Text(check.status, style=f"bold {style}"), check.detail
        )

    required_failures = [c for c in checks if c.required and not c.ok]
    optional_failures = [c for c in checks if not c.required and not c.ok]

    if required_failures:
        verdict = Text("\nUNHEALTHY", style=f"bold {ui.SYNTH}")
        verdict.append(
            f" — {len(required_failures)} required check(s) failed.", style=ui.MUTED
        )
    elif optional_failures:
        verdict = Text("\nHEALTHY", style=f"bold {ui.HUMAN}")
        verdict.append(
            f" — {len(optional_failures)} optional feature(s) unavailable.",
            style=ui.MUTED,
        )
    else:
        verdict = Text("\nHEALTHY", style=f"bold {ui.HUMAN}")
        verdict.append(" — everything checks out.", style=ui.MUTED)

    body = [table, verdict]

    remedies = [c for c in checks if not c.ok and c.remedy]
    if remedies:
        hint = Text("\nSuggested fixes:\n", style=f"bold {ui.NEUTRAL}")
        for check in remedies:
            hint.append(f"  {check.name}: ", style=ui.MUTED)
            hint.append(f"{check.remedy}\n", style="default")
        body.append(hint)

    return ui.section("DOCTOR", Group(*body), style=ui.BRAND)
