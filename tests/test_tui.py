"""The terminal interface.

Driven headlessly through Textual's Pilot, so these are real interaction tests
rather than import checks: the app is mounted, every pane is rendered, and each
action is invoked the way a key press would invoke it.
"""

from __future__ import annotations

import asyncio

import pytest

from loraai.analysis.payload import encode_tags
from loraai.config import Config
from loraai.tui.app import PANES, LoraaiApp
from loraai.tui.widgets import meter, severity_text
from loraai.models import Severity

from .samples import AI_STYLE, ARABIC_PROSE, ZWSP

# asyncio_mode = "auto" in pyproject.toml means async tests need no marker,
# and a module-level one would wrongly tag the synchronous widget tests.

TAINTED = "Visible text here. " + encode_tags("HIDDEN-PAYLOAD") + f"more{ZWSP}text"
SIZE = (120, 44)


async def _settled(pilot, app, attempts: int = 40):
    """Wait for the analysis worker to finish."""
    for _ in range(attempts):
        await pilot.pause()
        if app.analysis is not None:
            return app.analysis
        await asyncio.sleep(0.02)
    raise AssertionError("analysis never completed")


class TestLifecycle:
    async def test_app_mounts_and_quits(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.is_running

    async def test_every_pane_renders(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            for pane, _label, _key in PANES:
                app.action_show_pane(pane)
                await pilot.pause()
                assert app.query_one("#switcher").current == pane

    async def test_starts_empty_without_input(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.analysis is None
            assert app.query_one("#switcher").current == "input"

    async def test_accepts_a_custom_config(self):
        config = Config()
        config.clean.profile = "aggressive"
        app = LoraaiApp(config=config)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.query_one("#clean-profile").value == "aggressive"


class TestAnalysis:
    async def test_initial_text_is_analysed(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            analysis = await _settled(pilot, app)
            assert analysis.statistics.words > 100
            assert app.query_one("#switcher").current == "dashboard"

    async def test_hidden_payload_reaches_the_ui(self):
        app = LoraaiApp(initial_text=TAINTED)
        async with app.run_test(size=SIZE) as pilot:
            analysis = await _settled(pilot, app)
            assert len(analysis.unicode.payloads) == 1
            assert analysis.unicode.payloads[0].decoded == "HIDDEN-PAYLOAD"
            app.action_show_pane("unicode")
            await pilot.pause()
            assert "DECODED" in app.query_one("#uni-payloads")._title

    async def test_unicode_table_is_populated(self):
        app = LoraaiApp(initial_text=TAINTED)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            assert app.query_one("#uni-table").row_count > 0

    async def test_marker_table_is_populated(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            assert app.query_one("#mark-table").row_count > 0

    async def test_arabic_input(self):
        app = LoraaiApp(initial_text=ARABIC_PROSE)
        async with app.run_test(size=SIZE) as pilot:
            analysis = await _settled(pilot, app)
            assert analysis.source.language == "ar"


class TestActions:
    async def test_clean(self):
        app = LoraaiApp(initial_text=TAINTED)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            app.action_run_clean()
            await pilot.pause()
            assert app.clean_result is not None
            assert app.clean_result.semantic_preserved
            assert ZWSP not in app.clean_result.cleaned

    async def test_humanize(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            app.action_run_humanize()
            await pilot.pause()
            assert app.humanize_result is not None
            assert app.humanize_result.marker_after < app.humanize_result.marker_before

    async def test_diff_after_humanize(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            app.action_run_humanize()
            await pilot.pause()
            app._do_diff()
            await pilot.pause()
            assert app.query_one("#switcher").current == "diff"

    async def test_adopting_a_result_re_analyses(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            before = await _settled(pilot, app)
            app.action_run_humanize()
            await pilot.pause()
            app._adopt_humanize()
            await pilot.pause()
            await asyncio.sleep(0.1)
            await pilot.pause()
            assert app.analysis is not None
            assert app.analysis.markers.total < before.markers.total

    async def test_clear_resets_state(self):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            app._do_clear()
            await pilot.pause()
            assert app.analysis is None
            assert app.query_one("#editor").text == ""

    async def test_report_export(self, tmp_path):
        app = LoraaiApp(initial_text=AI_STYLE)
        async with app.run_test(size=SIZE) as pilot:
            await _settled(pilot, app)
            target = tmp_path / "out.html"
            app.query_one("#report-path").value = str(target)
            app.query_one("#report-format").value = "html"
            app._do_report()
            await pilot.pause()
            assert target.exists() and target.stat().st_size > 500

    async def test_theme_toggle(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            first = app.theme
            app.action_toggle_theme()
            await pilot.pause()
            assert app.theme != first
            app.action_toggle_theme()
            await pilot.pause()
            assert app.theme == first

    async def test_actions_without_input_do_not_crash(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.action_run_analysis()
            app.action_run_clean()
            app.action_run_humanize()
            app._do_diff()
            app._do_report()
            await pilot.pause()
            assert app.is_running

    async def test_missing_file_reports_cleanly(self, tmp_path):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._load_file(str(tmp_path / "absent.txt"))
            await pilot.pause()
            assert app.is_running
            assert app.analysis is None

    async def test_loading_a_real_file(self, tmp_text_file):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app._load_file(tmp_text_file(AI_STYLE))
            analysis = await _settled(pilot, app)
            assert analysis.statistics.words > 100


class TestModals:
    async def test_help_opens_and_closes(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.action_help()
            await pilot.pause()
            assert len(app.screen_stack) == 2
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    async def test_about_opens(self):
        app = LoraaiApp()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            app.action_about()
            await pilot.pause()
            assert len(app.screen_stack) == 2

    async def test_help_states_the_watermark_limit(self):
        from loraai.tui.screens import HELP_TEXT

        assert "statistical" in HELP_TEXT
        assert "No local tool can do it" in HELP_TEXT


class TestWidgets:
    def test_meter_marks_a_position(self):
        assert "●" in meter(0.5).plain

    @pytest.mark.parametrize("score", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_meter_handles_the_full_range(self, score):
        assert meter(score).plain.count("●") == 1

    def test_severity_colouring(self):
        assert severity_text(Severity.CRITICAL).plain == "critical"
