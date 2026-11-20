"""Command-line interface.

Uses Click's runner rather than a subprocess, so failures surface as real
tracebacks. What is checked: every command runs, every input route works, and
every user error produces a clean message and a sensible exit code -- never a
traceback.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from loraai.cli.main import cli

from .samples import AI_STYLE, ARABIC_PROSE, HUMAN_STYLE, ZWSP


@pytest.fixture
def run():
    runner = CliRunner()

    def invoke(args, **kwargs):
        return runner.invoke(cli, args, catch_exceptions=False, **kwargs)

    return invoke


class TestTopLevel:
    def test_help(self, run):
        result = run(["--help"])
        assert result.exit_code == 0
        for command in ("analyze", "inspect", "clean", "humanize", "diff", "report"):
            assert command in result.output

    def test_version(self, run):
        assert "loraai" in run(["--version"]).output

    def test_version_command(self, run):
        assert run(["version"]).exit_code == 0

    @pytest.mark.parametrize(
        "command",
        ["analyze", "inspect", "clean", "humanize", "diff", "report", "doctor",
         "config", "tui", "version"],
    )
    def test_every_command_has_help(self, run, command):
        result = run([command, "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output


class TestGlobalFlags:
    """Global flags must work on either side of the subcommand."""

    @pytest.mark.parametrize(
        "args",
        [
            ["doctor", "--quiet"],
            ["--quiet", "doctor"],
            ["analyze", "-t", "hello world here", "--no-color"],
            ["--no-color", "analyze", "-t", "hello world here"],
            ["analyze", "-t", "hello world here", "-v"],
        ],
    )
    def test_flag_position_does_not_matter(self, run, args):
        assert run(args).exit_code == 0

    def test_a_flag_shaped_value_is_not_hoisted(self, run):
        # "--quiet" here is the text being analysed, not a flag.
        payload = json.loads(run(["analyze", "-t", "--quiet", "--json"]).output)
        assert payload["source"]["char_count"] == len("--quiet")


class TestStdin:
    def test_analyze_reads_piped_text(self, run):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--json"], input=AI_STYLE)
        assert result.exit_code == 0
        assert json.loads(result.output)["statistics"]["words"] > 100

    def test_clean_reads_piped_text(self, run):
        runner = CliRunner()
        result = runner.invoke(cli, ["clean", "--quiet-text"], input=f"a{ZWSP}b")
        assert result.output == "ab"

    def test_explicit_stdin_flag(self, run):
        runner = CliRunner()
        result = runner.invoke(cli, ["inspect", "--stdin", "--json"], input=f"x{ZWSP}y")
        assert json.loads(result.output)["unicode"]["total_findings"] == 1

    def test_empty_stdin_is_an_error(self, run):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze"], input="")
        assert result.exit_code == 2
        assert "stdin" in result.output.lower()
        assert "Traceback" not in result.output


class TestAnalyze:
    def test_text_input(self, run):
        result = run(["analyze", "-t", AI_STYLE])
        assert result.exit_code == 0
        assert "SYNTHETIC-TEXT ASSESSMENT" in result.output

    def test_file_input(self, run, tmp_text_file):
        result = run(["analyze", "-f", tmp_text_file(AI_STYLE)])
        assert result.exit_code == 0

    def test_json_output_is_valid(self, run):
        payload = json.loads(run(["analyze", "-t", AI_STYLE, "--json"]).output)
        assert payload["schema_version"]
        assert "synthetic_signal" in payload

    def test_caveats_are_always_shown(self, run):
        assert "HOW TO READ THIS" in run(["analyze", "-t", AI_STYLE]).output

    def test_provenance_is_always_shown(self, run):
        output = run(["analyze", "-t", AI_STYLE]).output
        assert "PROVENANCE MARKING" in output
        assert "NOT DETECTABLE" in output

    def test_fail_on_severity(self, run):
        clean_result = run(["analyze", "-t", HUMAN_STYLE, "--fail-on", "high"])
        assert clean_result.exit_code == 0
        dirty = run(["analyze", "-t", f"a{ZWSP}b " + HUMAN_STYLE, "--fail-on", "high"])
        assert dirty.exit_code == 5

    def test_arabic(self, run):
        assert run(["analyze", "-t", ARABIC_PROSE]).exit_code == 0

    def test_no_color(self, run):
        assert "\x1b[" not in run(["--no-color", "analyze", "-t", AI_STYLE]).output


class TestInspect:
    def test_finds_hidden_payload(self, run):
        from loraai.analysis.payload import encode_tags

        result = run(["inspect", "-t", "visible" + encode_tags("SECRET-abc")])
        assert "HIDDEN PAYLOAD DECODED" in result.output
        assert "SECRET-abc" in result.output

    def test_json_output(self, run):
        payload = json.loads(run(["inspect", "-t", f"a{ZWSP}b", "--json"]).output)
        assert payload["unicode"]["total_findings"] == 1

    def test_clean_text(self, run):
        assert "No invisible" in run(["inspect", "-t", "plain ascii text"]).output


class TestClean:
    def test_removes_invisible_characters(self, run, tmp_path):
        out = tmp_path / "out.txt"
        result = run(["clean", "-t", f"a{ZWSP}b", "-o", str(out)])
        assert result.exit_code == 0
        assert out.read_text() == "ab"

    def test_dry_run_writes_nothing(self, run, tmp_path):
        out = tmp_path / "never.txt"
        result = run(["clean", "-t", f"a{ZWSP}b", "--dry-run", "-o", str(out)])
        assert "DRY RUN" in result.output
        assert not out.exists()

    def test_quiet_text_prints_only_the_result(self, run):
        assert run(["clean", "-t", f"a{ZWSP}b", "--quiet-text"]).output == "ab"

    def test_in_place_with_backup(self, run, tmp_text_file):
        from pathlib import Path

        path = Path(tmp_text_file(f"x{ZWSP}y"))
        result = run(["clean", "-f", str(path), "--in-place"])
        assert result.exit_code == 0
        assert path.read_text() == "xy"
        assert path.with_suffix(".txt.bak").read_text() == f"x{ZWSP}y"

    def test_in_place_requires_a_file(self, run):
        result = run(["clean", "-t", "abc", "--in-place"])
        assert result.exit_code == 1
        assert "needs a file" in result.output

    def test_arabic_is_preserved(self, run):
        assert run(["clean", "-t", ARABIC_PROSE, "--quiet-text"]).output == ARABIC_PROSE

    @pytest.mark.parametrize("profile", ["safe", "standard", "aggressive"])
    def test_every_profile(self, run, profile):
        assert run(["clean", "-t", f"a{ZWSP}b", "-p", profile, "--quiet-text"]).output == "ab"


class TestHumanize:
    def test_reduces_markers(self, run):
        result = run(["humanize", "-t", AI_STYLE, "-I", "3"])
        assert result.exit_code == 0
        assert "HUMANIZE" in result.output

    def test_quiet_text(self, run):
        output = run(["humanize", "-t", AI_STYLE, "-I", "3", "--quiet-text"]).output
        assert "delve" not in output
        assert output.strip()

    def test_json_output(self, run):
        payload = json.loads(
            run(["humanize", "-t", AI_STYLE, "--json"]).output
        )
        assert payload["provider"] == "offline"
        assert payload["markers_after"] <= payload["markers_before"]

    def test_diff_flag(self, run):
        assert "DIFF" in run(["humanize", "-t", AI_STYLE, "-I", "3", "--diff"]).output

    def test_writes_output_file(self, run, tmp_path):
        out = tmp_path / "h.txt"
        run(["humanize", "-t", AI_STYLE, "-o", str(out)])
        assert out.exists() and out.read_text().strip()

    def test_unconfigured_provider_fails_cleanly(self, run, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = run(["humanize", "-t", "hello there", "--provider", "anthropic"])
        assert result.exit_code == 4
        assert "ANTHROPIC_API_KEY" in result.output

    @pytest.mark.parametrize(
        "style",
        ["natural", "concise", "professional", "academic", "conversational"],
    )
    def test_every_style(self, run, style):
        assert run(["humanize", "-t", AI_STYLE, "-s", style]).exit_code == 0


class TestDiffCommand:
    def test_files(self, run, tmp_text_file):
        a = tmp_text_file("one two three", "a.txt")
        b = tmp_text_file("one two four", "b.txt")
        assert "DIFF" in run(["diff", a, b]).output

    def test_literal_text(self, run):
        assert run(["diff", "--text", "abc", "abd"]).exit_code == 0

    def test_unified(self, run, tmp_text_file):
        a = tmp_text_file("x\ny", "a.txt")
        b = tmp_text_file("x\nz", "b.txt")
        assert "---" in run(["diff", a, b, "--unified"]).output

    def test_missing_file(self, run, tmp_path):
        result = run(["diff", str(tmp_path / "no.txt"), str(tmp_path / "also.txt")])
        assert result.exit_code == 2


class TestReportCommand:
    @pytest.mark.parametrize("fmt", ["json", "html", "markdown"])
    def test_every_format(self, run, tmp_path, fmt):
        out = tmp_path / f"r.{fmt}"
        result = run(["report", "-t", AI_STYLE, "--format", fmt, "-o", str(out)])
        assert result.exit_code == 0
        assert out.stat().st_size > 200

    def test_schema_flag(self, run):
        assert json.loads(run(["report", "--schema"]).output)["schema_version"]

    def test_includes_optional_sections(self, run, tmp_path):
        out = tmp_path / "r.json"
        run(["report", "-t", AI_STYLE, "-o", str(out), "--include-clean",
             "--include-humanize"])
        payload = json.loads(out.read_text())
        assert "cleaning" in payload and "humanization" in payload


class TestErrorHandling:
    """No expected failure may produce a traceback."""

    def test_no_input(self, run):
        result = run(["analyze"])
        assert result.exit_code == 2
        assert "error:" in result.output
        assert "Traceback" not in result.output

    def test_two_inputs(self, run, tmp_text_file):
        result = run(["analyze", "-t", "x", "-f", tmp_text_file("y")])
        assert result.exit_code == 2
        assert "More than one input" in result.output

    def test_missing_file(self, run, tmp_path):
        result = run(["analyze", "-f", str(tmp_path / "absent.txt")])
        assert result.exit_code == 2
        assert "File not found" in result.output
        assert "hint:" in result.output

    def test_binary_file(self, run, tmp_path):
        path = tmp_path / "b.bin"
        path.write_bytes(bytes(range(256)) * 40)
        result = run(["analyze", "-f", str(path)])
        assert result.exit_code == 2
        assert "binary" in result.output.lower()

    def test_bad_config(self, run, tmp_path):
        config = tmp_path / "bad.toml"
        config.write_text('[clean]\nprofile = "nuclear"\n')
        result = run(["--config", str(config), "analyze", "-t", "hello"])
        assert result.exit_code == 3
        assert "not valid" in result.output

    def test_invalid_profile_choice(self, run):
        runner = CliRunner()
        result = runner.invoke(cli, ["clean", "-t", "x", "-p", "nope"])
        assert result.exit_code == 2


class TestDoctorAndConfig:
    def test_doctor_runs(self, run):
        result = run(["doctor"])
        assert "DOCTOR" in result.output
        assert "Engine self-test" in result.output

    def test_doctor_json(self, run):
        payload = json.loads(run(["doctor", "--json"]).output)
        assert payload["healthy"] is True
        names = {c["name"] for c in payload["checks"]}
        assert "Engine self-test" in names

    def test_doctor_self_test_passes(self, run):
        payload = json.loads(run(["doctor", "--json"]).output)
        engine = next(c for c in payload["checks"] if c["name"] == "Engine self-test")
        assert engine["ok"] is True

    def test_config_path(self, run):
        assert "config.toml" in run(["config", "path"]).output

    def test_config_show(self, run):
        assert json.loads(run(["config", "show"]).output)["clean"]["profile"]


class TestActionColumnTellsTheTruth:
    """The Action column must not promise what the default profile declines.

    inspect used to print "remove" for an orphan joiner that the safe profile
    kept, and "replace" for a homoglyph no default run would touch. The column
    now names the profile that performs the action, and the profile is worked
    out by running the cleaner, so it cannot drift from the behaviour.
    """

    def test_homoglyph_action_names_the_profile_that_does_it(self, run):
        result = run(["inspect", "-t", "аbc"])
        assert result.exit_code in (0, 5)
        assert "aggressive" in result.output
        assert "default safe profile" in result.output

    def test_action_the_default_profile_performs_is_unqualified(self, run):
        result = run(["inspect", "-t", "a​b"])
        assert "remove" in result.output
        assert "remove →" not in result.output

    @pytest.mark.parametrize("text", ["a​b", "end.️", "x,‌y"])
    def test_everything_marked_remove_is_gone_after_a_default_clean(
        self, run, text
    ):
        """The promise the column makes, checked against what clean does."""
        from loraai.analysis.unicode_forensics import scan
        from loraai.cleaning import clean

        cleaned = clean(text).cleaned
        for finding in scan(text).findings:
            if finding.recommended_action == "remove":
                assert chr(finding.codepoint) not in cleaned, finding.code

    def test_profiles_acting_on_is_derived_from_real_behaviour(self):
        from loraai.cleaning.cleaner import profiles_acting_on

        acting = profiles_acting_on("аbc a​b end.️ a‬b")
        assert acting["U+200B"] == "safe"
        assert acting["U+FE0F"] == "safe"
        assert acting["U+202C"] == "standard"
        assert acting["U+0430"] == "aggressive"

    def test_a_character_no_profile_touches_is_reported_as_such(self):
        from loraai.cleaning.cleaner import profiles_acting_on

        assert "U+0041" not in profiles_acting_on("ABC")
