"""Diff engine, report writers, configuration and terminal sanitisation."""

from __future__ import annotations

import json

import pytest

from loraai import textio
from loraai.analysis import analyze
from loraai.cleaning import clean
from loraai.config import Config, load, resolve_language, write_default
from loraai.diffing import diff, summary
from loraai.errors import ConfigError
from loraai.humanize import humanize
from loraai.reports import FORMATS, render
from loraai.reports.json_report import schema_info
from loraai.sanitize import (
    escape_for_terminal,
    one_line,
    redact_secrets,
    strip_ansi,
)
from loraai.version import REPORT_SCHEMA_VERSION

from .samples import AI_STYLE, ARABIC_PROSE, ZWSP


class TestDiff:
    def test_identical_texts(self):
        result = diff("same text", "same text")
        assert not result.changed
        assert result.stats.similarity == 1.0

    @pytest.mark.parametrize("mode", ["line", "word", "char"])
    def test_every_mode(self, mode):
        result = diff("the quick fox", "the slow fox", mode=mode)
        assert result.changed
        assert result.mode == mode

    def test_word_statistics(self):
        result = diff("one two three", "one two three four", mode="word")
        assert result.stats.words_added == 1
        assert result.stats.words_removed == 0
        assert result.stats.words_unchanged == 3

    def test_invisible_change_needs_char_mode(self):
        before, after = "hello world", f"hello{ZWSP} world"
        assert diff(before, after, mode="char").changed

    def test_unified_output(self):
        assert "---" in diff("a\nb", "a\nc", mode="line").unified

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="Unknown diff mode"):
            diff("a", "b", mode="sideways")

    def test_summary_pairs(self):
        assert dict(summary(diff("a b", "a c")))["Words before"] == "2"

    def test_serialisable(self):
        json.dumps(diff("a", "b").to_dict())


class TestReports:
    @pytest.fixture
    def analysis(self):
        return analyze(textio.from_text(AI_STYLE))

    def test_json_is_valid_and_versioned(self, analysis):
        payload = json.loads(render(analysis, "json"))
        assert payload["schema_version"] == REPORT_SCHEMA_VERSION
        assert "synthetic_signal" in payload
        assert "provenance_marking" in payload

    def test_json_schema_top_level_keys(self, analysis):
        payload = json.loads(render(analysis, "json"))
        for key in (
            "source", "statistics", "style", "unicode", "ai_markers",
            "synthetic_signal", "provenance_marking", "warnings",
        ):
            assert key in payload

    def test_json_states_the_watermark_limit(self, analysis):
        payload = json.loads(render(analysis, "json"))
        statistical = payload["provenance_marking"]["statistical_watermark"]
        assert statistical["detectable_locally"] is False
        assert "NOT DETECTABLE" in statistical["status"]

    def test_html_is_self_contained(self, analysis):
        html = render(analysis, "html")
        assert html.startswith("<!doctype html>")
        # No external fetches of any kind.
        for token in ("http://", "src=", "@import"):
            assert token not in html.split("<footer>")[0]
        assert "prefers-color-scheme" in html

    def test_markdown_has_the_caveats(self, analysis):
        markdown = render(analysis, "markdown")
        assert "# loraai report" in markdown
        assert "not proof of authorship" in markdown

    @pytest.mark.parametrize("fmt", sorted(set(FORMATS)))
    def test_every_format_renders(self, analysis, fmt):
        assert len(render(analysis, fmt)) > 200

    def test_unknown_format(self, analysis):
        with pytest.raises(ValueError, match="Unknown report format"):
            render(analysis, "pdf")

    def test_optional_sections(self, analysis):
        payload = json.loads(
            render(
                analysis,
                "json",
                clean=clean(AI_STYLE, "safe"),
                humanize=humanize(AI_STYLE, language="en"),
            )
        )
        assert "cleaning" in payload and "humanization" in payload

    def test_secrets_are_redacted(self):
        analysis = analyze(textio.from_text('api_key = "abcdef1234567890XYZ" ' * 20))
        assert "abcdef1234567890XYZ" not in render(analysis, "json")

    def test_schema_info(self):
        assert schema_info()["schema_version"] == REPORT_SCHEMA_VERSION

    def test_arabic_survives_json(self):
        analysis = analyze(textio.from_text(ARABIC_PROSE))
        payload = json.loads(render(analysis, "json"))
        assert payload["source"]["language"] == "ar"


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.clean.profile == "safe"
        assert config.humanize.intensity == 2

    def test_round_trip(self, tmp_path):
        path = write_default(tmp_path / "config.toml")
        loaded = load(path)
        assert loaded.humanize.style == "natural"
        assert loaded.source_path == str(path)

    def test_missing_file_uses_defaults(self, tmp_path):
        assert load(tmp_path / "absent.toml").source_path is None

    def test_invalid_value_is_rejected(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text('[clean]\nprofile = "nuclear"\n')
        with pytest.raises(ConfigError) as excinfo:
            load(path)
        assert "aggressive" in excinfo.value.hint

    def test_unknown_key_is_rejected(self, tmp_path):
        path = tmp_path / "unknown.toml"
        path.write_text("[clean]\nwibble = 1\n")
        with pytest.raises(ConfigError, match="Unknown key"):
            load(path)

    def test_malformed_toml_is_rejected(self, tmp_path):
        path = tmp_path / "broken.toml"
        path.write_text("[clean\n")
        with pytest.raises(ConfigError, match="not valid TOML"):
            load(path)

    def test_intensity_range_is_enforced(self, tmp_path):
        path = tmp_path / "range.toml"
        path.write_text("[humanize]\nintensity = 9\n")
        with pytest.raises(ConfigError, match="1 to 3"):
            load(path)

    def test_template_never_contains_a_key(self, tmp_path):
        content = (tmp_path / "c.toml").write_text("") or write_default(
            tmp_path / "c2.toml"
        ).read_text()
        assert "sk-" not in content
        assert "API keys are NEVER stored here" in content

    def test_language_resolution(self):
        config = Config()
        assert resolve_language(config, "ar") == "ar"
        config.general.language = "en"
        assert resolve_language(config, "ar") == "en"

    def test_overwrite_requires_force(self, tmp_path):
        path = write_default(tmp_path / "c.toml")
        with pytest.raises(ConfigError, match="already exists"):
            write_default(path)
        assert write_default(path, overwrite=True) == path


class TestSanitize:
    def test_ansi_is_stripped(self):
        assert strip_ansi("a\x1b[31mred\x1b[0m") == "ared"

    def test_escape_neutralises_control_and_bidi(self):
        escaped = escape_for_terminal("x\x1b[2Jy‮z")
        assert "\x1b" not in escaped
        assert "‮" not in escaped
        assert "<U+202E>" in escaped

    def test_invisible_characters_are_revealed(self):
        assert "<U+200B>" in escape_for_terminal(f"a{ZWSP}b")

    def test_newlines_and_tabs_survive(self):
        assert escape_for_terminal("a\nb\tc") == "a\nb\tc"

    def test_one_line_truncates(self):
        assert len(one_line("x" * 500, 40)) == 40

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-abcdefghijklmnopqrstuvwxyz",
            "sk-ant-abcdefghijklmnop1234567",
            "ghp_abcdefghijklmnopqrstuvwxyz12",
            "AKIAIOSFODNN7EXAMPLE",
        ],
    )
    def test_secrets_are_redacted(self, secret):
        assert secret not in redact_secrets(f"token: {secret} end")

    def test_ordinary_text_is_untouched(self):
        text = "Nothing secret here, just prose."
        assert redact_secrets(text) == text
