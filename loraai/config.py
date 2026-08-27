"""Configuration.

Layered, in increasing precedence: built-in defaults, the config file,
environment variables, then command-line flags. Every layer is optional, so
the tool works with no configuration at all.

Secrets policy
--------------
API keys are read from environment variables and are never written to the
config file. The file stores the *name* of the variable to read, not its
value, so a config file is safe to commit or share.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from .errors import ConfigError

try:  # pragma: no cover - version-dependent import
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

APP_NAME = "loraai"
CONFIG_FILENAME = "config.toml"


def config_dir() -> Path:
    """Platform-appropriate configuration directory."""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_path() -> Path:
    """Full path to the config file (which need not exist)."""
    return config_dir() / CONFIG_FILENAME


@dataclass
class GeneralConfig:
    language: str = "auto"          # auto | en | ar | mixed
    color: str = "auto"             # auto | always | never
    max_bytes: int = 32 * 1024 * 1024


@dataclass
class AnalysisConfig:
    decode_hidden_payloads: bool = True
    prose_from_code: bool = True
    min_words_for_verdict: int = 50


@dataclass
class CleanConfig:
    profile: str = "safe"           # safe | standard | aggressive
    backup: bool = True             # write a .bak before overwriting in place


@dataclass
class HumanizeConfig:
    style: str = "natural"
    intensity: int = 2
    provider: str = "offline"       # offline | anthropic | openai | openrouter | ollama
    model: str = ""                 # empty means the provider default
    clean_first: bool = True


@dataclass
class TuiConfig:
    theme: str = "loraai-dark"
    show_footer: bool = True
    animate: bool = True


@dataclass
class Config:
    """The complete resolved configuration."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    clean: CleanConfig = field(default_factory=CleanConfig)
    humanize: HumanizeConfig = field(default_factory=HumanizeConfig)
    tui: TuiConfig = field(default_factory=TuiConfig)
    #: Path the config was loaded from, or ``None`` when using defaults.
    source_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("source_path", None)
        return data


_SECTION_TYPES = {
    "general": GeneralConfig,
    "analysis": AnalysisConfig,
    "clean": CleanConfig,
    "humanize": HumanizeConfig,
    "tui": TuiConfig,
}

_VALID_VALUES = {
    ("general", "language"): {"auto", "en", "ar", "mixed"},
    ("general", "color"): {"auto", "always", "never"},
    ("clean", "profile"): {"safe", "standard", "aggressive"},
    ("humanize", "style"): {
        "natural", "concise", "professional", "academic", "conversational"
    },
    ("humanize", "provider"): {
        "offline", "anthropic", "openai", "openrouter", "ollama"
    },
}


def _validate(section: str, key: str, value: Any) -> Any:
    allowed = _VALID_VALUES.get((section, key))
    if allowed is not None and value not in allowed:
        raise ConfigError(
            f"[{section}] {key} = {value!r} is not valid.",
            hint=f"Allowed values: {', '.join(sorted(allowed))}.",
        )
    if section == "humanize" and key == "intensity":
        if not isinstance(value, int) or not 1 <= value <= 3:
            raise ConfigError(
                f"[humanize] intensity must be an integer from 1 to 3, got {value!r}."
            )
    if section == "general" and key == "max_bytes":
        if not isinstance(value, int) or value <= 0:
            raise ConfigError(
                f"[general] max_bytes must be a positive integer, got {value!r}."
            )
    return value


def load(path: Optional[Path] = None) -> Config:
    """Load configuration, falling back to defaults when no file exists."""
    target = Path(path) if path else config_path()
    config = Config()

    if not target.exists():
        return config

    if tomllib is None:  # pragma: no cover - only on 3.10 without tomli
        raise ConfigError(
            "Cannot read the config file: no TOML parser available.",
            hint="Install tomli (pip install tomli) or use Python 3.11+.",
        )

    try:
        with target.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"Cannot read {target}: {exc}") from None
    except Exception as exc:  # tomllib.TOMLDecodeError and friends
        raise ConfigError(
            f"{target} is not valid TOML: {exc}",
            hint="Fix the syntax, or delete the file to fall back to defaults.",
        ) from None

    for section_name, section_type in _SECTION_TYPES.items():
        values = raw.get(section_name)
        if not isinstance(values, dict):
            continue
        current = getattr(config, section_name)
        known = {f for f in section_type.__dataclass_fields__}
        for key, value in values.items():
            if key not in known:
                raise ConfigError(
                    f"Unknown key [{section_name}] {key!r} in {target}.",
                    hint=f"Valid keys: {', '.join(sorted(known))}.",
                )
            setattr(current, key, _validate(section_name, key, value))

    config.source_path = str(target)
    return config


DEFAULT_CONFIG_TEMPLATE = """\
# loraai configuration
# Every value below is a default; delete any line to keep the built-in value.

[general]
# auto | en | ar | mixed
language = "auto"
# auto | always | never
color = "auto"
max_bytes = 33554432

[analysis]
decode_hidden_payloads = true
# For source files, run writing-style metrics on comments only.
prose_from_code = true
min_words_for_verdict = 50

[clean]
# safe | standard | aggressive
profile = "safe"
# Write a .bak alongside the original when cleaning a file in place.
backup = true

[humanize]
# natural | concise | professional | academic | conversational
style = "natural"
# 1 (light) .. 3 (thorough)
intensity = 2
# offline | anthropic | openai | openrouter | ollama
provider = "offline"
# Leave empty for the provider's default model.
model = ""
clean_first = true

[tui]
theme = "loraai-dark"
show_footer = true
animate = true

# API keys are NEVER stored here. Providers read them from the environment:
#   ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY
# so this file stays safe to share or commit.
"""


def write_default(path: Optional[Path] = None, *, overwrite: bool = False) -> Path:
    """Write a commented default config file and return its path."""
    target = Path(path) if path else config_path()
    if target.exists() and not overwrite:
        raise ConfigError(
            f"{target} already exists.",
            hint="Pass --force to overwrite it.",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot write {target}: {exc}") from None
    return target


def resolve_language(config: Config, detected: str) -> str:
    """Pick the language to analyse with: configured, else detected."""
    configured = config.general.language
    if configured and configured != "auto":
        return configured
    return detected if detected != "unknown" else "en"
