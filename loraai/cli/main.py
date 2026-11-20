"""The loraai command line.

Design notes
------------
* Every command that takes text accepts it three ways: ``--text``, ``--file``,
  or piped stdin. One resolver enforces "exactly one of these" with a message
  that says what to do next.
* ``loraai`` with no arguments opens the TUI, because that is the primary
  interface. The subcommands exist for scripting and CI.
* No expected failure produces a traceback. :class:`~loraai.errors.LoraError`
  carries a message, an optional hint, and an exit code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import click
from rich.text import Text

from .. import config as config_module
from .. import textio
from ..analysis import analyze as run_analysis
from ..analysis.provenance import summary_lines
from ..cleaning import clean as run_clean
from ..cleaning.cleaner import profiles_acting_on
from ..cleaning.rules import PROFILES
from ..diffing import diff as run_diff
from ..errors import LoraError, ProviderError
from ..humanize import humanize as run_humanize
from ..humanize.providers import get_provider
from ..models import Severity
from ..reports import FORMATS, render as render_report
from ..version import get_version
from . import render as ui

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "max_content_width": 100,
}

_SEVERITY_ORDER = ["none", "info", "low", "medium", "high", "critical"]


class LoraaiGroup(click.Group):
    """A group that accepts the global flags on either side of the subcommand.

    ``loraai doctor --quiet`` is what people actually type, and rejecting it in
    favour of ``loraai --quiet doctor`` is a pointless papercut. Recognised
    global flags are hoisted ahead of the subcommand before Click parses.

    A flag is only hoisted when it is not the value of a preceding option, so
    ``loraai analyze -t "--quiet"`` still passes that string through as text.
    """

    GLOBAL_FLAGS = frozenset({"--no-color", "--quiet", "-q", "--verbose", "-v"})

    def parse_args(self, ctx, args):
        name = next((a for a in args if not a.startswith("-") and a in self.commands), None)
        value_options: set[str] = set()
        if name is not None:
            for param in self.commands[name].params:
                if isinstance(param, click.Option) and not param.is_flag:
                    value_options.update(param.opts)
                    value_options.update(param.secondary_opts)

        hoisted: list[str] = []
        rest: list[str] = []
        previous: str | None = None
        for arg in args:
            if arg in self.GLOBAL_FLAGS and previous not in value_options:
                hoisted.append(arg)
            else:
                rest.append(arg)
            previous = arg
        return super().parse_args(ctx, hoisted + rest)


class Context:
    """Shared state threaded through every command."""

    def __init__(self) -> None:
        self.console = ui.make_console()
        self.config = config_module.Config()
        self.quiet = False
        self.verbose = False
        self.json_output = False

    def out(self, *renderables) -> None:
        if self.quiet:
            return
        for renderable in renderables:
            self.console.print(renderable)

    def fail(self, error: LoraError) -> None:
        """Print a clean error and exit with its code."""
        stderr = ui.make_console()
        stderr.stderr = True
        text = Text()
        text.append("error: ", style=f"bold {ui.SYNTH}")
        text.append(error.message)
        if error.hint:
            text.append("\nhint:  ", style=f"bold {ui.NEUTRAL}")
            text.append(error.hint, style=ui.MUTED)
        stderr.print(text)
        raise SystemExit(error.exit_code)


pass_context = click.make_pass_decorator(Context, ensure=True)


def _load_input(
    ctx: Context, text: Optional[str], file: Optional[str], stdin_flag: bool
) -> textio.LoadedText:
    """Resolve one input from the three supported sources."""
    use_stdin = stdin_flag or (
        not text and not file and textio.stdin_has_data()
    )
    return textio.resolve(
        text=text,
        file=file,
        use_stdin=use_stdin,
        max_bytes=ctx.config.general.max_bytes,
    )


def input_options(func):
    """Attach the shared --text / --file / - input options."""
    func = click.option(
        "--text", "-t", "text_input", metavar="TEXT",
        help="Analyse this literal text.",
    )(func)
    func = click.option(
        "--file", "-f", "file_input", metavar="PATH",
        type=click.Path(dir_okay=False),
        help="Analyse this file.",
    )(func)
    func = click.option(
        "--stdin", "stdin_flag", is_flag=True,
        help="Read from standard input (also the default when text is piped).",
    )(func)
    return func


def _write_output(ctx: Context, path: Optional[str], content: str, label: str) -> None:
    """Write to a file, or to stdout when no path is given."""
    if not path:
        click.echo(content)
        return
    target = Path(path).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise LoraError(f"Cannot write {target}: {exc}") from None
    if not ctx.quiet:
        ctx.console.print(
            Text.assemble(
                ("wrote ", ui.MUTED), (str(target), f"bold {ui.ACCENT}"),
                (f"  ({len(content):,} bytes, {label})", ui.MUTED),
            )
        )


def _severity_at_least(actual: Severity, threshold: str) -> bool:
    if threshold == "none":
        return False
    return actual.rank >= _SEVERITY_ORDER.index(threshold) - 1


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@click.group(
    cls=LoraaiGroup,
    context_settings=CONTEXT_SETTINGS,
    invoke_without_command=True,
    help="""\
Text forensics, hidden-Unicode detection, AI-writing analysis and humanization.

Run with no arguments to open the TUI.

\b
Common uses:
  loraai                          open the interactive TUI
  loraai analyze -f article.md    full analysis of a file
  loraai analyze -t "some text"   analyse text directly
  cat a.txt | loraai analyze      analyse piped input
  loraai inspect -f doc.txt       hidden-character forensics only
  loraai clean -f doc.txt -o out  strip invisible characters
  loraai humanize -f draft.md     rewrite to read more naturally
""",
)
@click.option("--no-color", is_flag=True, help="Disable all colour output.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output.")
@click.option("--verbose", "-v", is_flag=True, help="Show additional detail.")
@click.option(
    "--config", "config_path", metavar="PATH", type=click.Path(dir_okay=False),
    help="Use this config file instead of the default location.",
)
@click.version_option(get_version(), "-V", "--version", prog_name="loraai")
@click.pass_context
def cli(click_ctx, no_color, quiet, verbose, config_path):
    ctx = Context()
    ctx.console = ui.make_console(no_color=no_color)
    ctx.quiet = quiet
    ctx.verbose = verbose
    click_ctx.obj = ctx

    try:
        ctx.config = config_module.load(Path(config_path) if config_path else None)
    except LoraError as error:
        ctx.fail(error)

    if click_ctx.invoked_subcommand is None:
        click_ctx.invoke(tui)


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@cli.command(
    help="Full analysis: hidden characters, writing style, and an AI-likelihood "
         "assessment."
)
@input_options
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@click.option(
    "--limit", default=20, show_default=True, metavar="N",
    help="Maximum findings shown per section.",
)
@click.option(
    "--fail-on", type=click.Choice(_SEVERITY_ORDER), default="none",
    show_default=True,
    help="Exit non-zero when a Unicode finding reaches this severity.",
)
@click.option("--no-decode", is_flag=True, help="Skip hidden-payload decoding.")
@pass_context
def analyze(ctx, text_input, file_input, stdin_flag, as_json, limit, fail_on, no_decode):
    try:
        loaded = _load_input(ctx, text_input, file_input, stdin_flag)
        result = run_analysis(
            loaded,
            decode_hidden=not no_decode and ctx.config.analysis.decode_hidden_payloads,
            prose_from_code=ctx.config.analysis.prose_from_code,
        )
    except LoraError as error:
        ctx.fail(error)
        return

    if as_json:
        click.echo(render_report(result, "json"))
    else:
        if not ctx.quiet:
            ui.banner(ctx.console, compact=True)
            ctx.console.print()
        ctx.out(*ui.render_full(result, verbose=ctx.verbose, limit=limit,
                                acting=profiles_acting_on(loaded.text)))

    if _severity_at_least(result.unicode.max_severity, fail_on):
        raise SystemExit(5)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


@cli.command(
    help="Unicode forensics only: invisible characters, bidi controls, "
         "homoglyphs, and any payload hidden inside them."
)
@input_options
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@click.option("--limit", default=40, show_default=True, help="Maximum findings shown.")
@click.option(
    "--fail-on", type=click.Choice(_SEVERITY_ORDER), default="none",
    show_default=True, help="Exit non-zero at this severity or above.",
)
@click.option("--all", "show_all", is_flag=True, help="Show every finding.")
@pass_context
def inspect(ctx, text_input, file_input, stdin_flag, as_json, limit, fail_on, show_all):
    try:
        loaded = _load_input(ctx, text_input, file_input, stdin_flag)
        result = run_analysis(loaded)
    except LoraError as error:
        ctx.fail(error)
        return

    if as_json:
        payload = {
            "source": loaded.source.to_dict(),
            "unicode": result.unicode.to_dict(),
            "provenance_marking": result.watermark.to_dict(),
        }
        import json as json_module

        click.echo(json_module.dumps(payload, indent=2, ensure_ascii=False))
    else:
        shown = result.unicode.total if show_all else limit
        payloads = ui.render_payloads(result.unicode)
        if payloads is not None:
            ctx.out(payloads)
        ctx.out(ui.render_unicode(result.unicode, limit=shown,
                                  acting=profiles_acting_on(loaded.text)))
        ctx.out(ui.render_provenance(result))
        if ctx.verbose:
            ctx.out(ui.render_references())

    if _severity_at_least(result.unicode.max_severity, fail_on):
        raise SystemExit(5)


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


@cli.command(
    help="Remove invisible and deceptive characters. Safe by default: Arabic "
         "joiners, diacritics and emoji sequences are preserved."
)
@input_options
@click.option(
    "--profile", "-p", type=click.Choice(sorted(PROFILES)), default=None,
    help="Cleaning profile (default: from config, else 'safe').",
)
@click.option("--output", "-o", metavar="PATH", help="Write the result here.")
@click.option(
    "--in-place", "-i", is_flag=True,
    help="Overwrite the input file (writes a .bak first unless disabled).",
)
@click.option("--no-backup", is_flag=True, help="Skip the .bak when using --in-place.")
@click.option(
    "--dry-run", "-n", is_flag=True, help="Show what would change; write nothing."
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@click.option("--quiet-text", is_flag=True, help="Print only the cleaned text.")
@pass_context
def clean(
    ctx, text_input, file_input, stdin_flag, profile, output, in_place,
    no_backup, dry_run, as_json, quiet_text,
):
    try:
        loaded = _load_input(ctx, text_input, file_input, stdin_flag)
        chosen = profile or ctx.config.clean.profile
        result = run_clean(loaded.text, chosen)

        if in_place:
            if loaded.source.origin != "file":
                raise LoraError(
                    "--in-place needs a file.",
                    hint="Use --file PATH, or --output PATH to write elsewhere.",
                )
            if dry_run:
                raise LoraError("--in-place and --dry-run are contradictory.")

        if quiet_text:
            click.echo(result.cleaned, nl=False)
            return

        if as_json:
            import json as json_module

            click.echo(
                json_module.dumps(
                    {**result.to_dict(), "cleaned_text": result.cleaned},
                    indent=2, ensure_ascii=False,
                )
            )
            return

        ctx.out(ui.render_clean(result, dry_run=dry_run))

        if dry_run:
            return

        if in_place:
            target = Path(loaded.source.path)
            if ctx.config.clean.backup and not no_backup:
                backup = target.with_suffix(target.suffix + ".bak")
                try:
                    backup.write_text(loaded.text, encoding="utf-8")
                except OSError as exc:
                    raise LoraError(f"Cannot write backup {backup}: {exc}") from None
                if not ctx.quiet:
                    ctx.console.print(
                        Text.assemble(("backup ", ui.MUTED), (str(backup), ui.ACCENT))
                    )
            _write_output(ctx, str(target), result.cleaned, "cleaned")
        elif output:
            _write_output(ctx, output, result.cleaned, "cleaned")
        elif not ctx.quiet:
            ctx.console.print(
                Text(
                    "\nNothing written. Use -o PATH, --in-place, or --quiet-text.",
                    style=ui.MUTED,
                )
            )
    except LoraError as error:
        ctx.fail(error)


# ---------------------------------------------------------------------------
# humanize
# ---------------------------------------------------------------------------


@cli.command(
    help="""\
Rewrite text so it reads as natural human writing.

Removes invisible characters, chat-assistant phrasing, inflated vocabulary,
formulaic transitions and mechanical sentence rhythm. Works fully offline;
pass --provider for genuine paraphrase via a language model.
"""
)
@input_options
@click.option(
    "--style", "-s",
    type=click.Choice(
        ["natural", "concise", "professional", "academic", "conversational"]
    ),
    default=None, help="Target register (default: from config, else 'natural').",
)
@click.option(
    "--intensity", "-I", type=click.IntRange(1, 3), default=None,
    help="1 light, 2 moderate, 3 thorough (default: from config, else 2).",
)
@click.option(
    "--provider", type=click.Choice(
        ["offline", "anthropic", "openai", "openrouter", "ollama"]
    ),
    default=None, help="Rewrite engine (default: from config, else 'offline').",
)
@click.option("--model", metavar="NAME", help="Override the provider's model.")
@click.option(
    "--language", "-L", type=click.Choice(["auto", "en", "ar", "mixed"]),
    default="auto", show_default=True, help="Rule set to apply.",
)
@click.option("--output", "-o", metavar="PATH", help="Write the result here.")
@click.option("--diff", "show_diff", is_flag=True, help="Show a before/after diff.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@click.option("--quiet-text", is_flag=True, help="Print only the rewritten text.")
@click.option("--no-clean", is_flag=True, help="Skip the invisible-character pass.")
@pass_context
def humanize(
    ctx, text_input, file_input, stdin_flag, style, intensity, provider, model,
    language, output, show_diff, as_json, quiet_text, no_clean,
):
    try:
        loaded = _load_input(ctx, text_input, file_input, stdin_flag)
        chosen_style = style or ctx.config.humanize.style
        chosen_intensity = intensity or ctx.config.humanize.intensity
        chosen_provider = provider or ctx.config.humanize.provider
        chosen_language = (
            loaded.source.language if language == "auto" else language
        )
        if chosen_language not in ("en", "ar", "mixed"):
            chosen_language = "en"

        result = run_humanize(
            loaded.text,
            language=chosen_language,
            style=chosen_style,
            intensity=chosen_intensity,
            clean_invisible=not no_clean and ctx.config.humanize.clean_first,
        )

        if chosen_provider != "offline":
            engine = get_provider(chosen_provider, model or ctx.config.humanize.model or None)
            if not ctx.quiet:
                ctx.console.print(
                    Text(
                        f"Rewriting via {chosen_provider} ({engine.config.model})...",
                        style=ui.MUTED,
                    )
                )
            rewritten = engine.rewrite(result.result, chosen_style, chosen_intensity)
            from ..analysis import markers as markers_module

            result.result = rewritten
            result.provider = chosen_provider
            result.marker_after = markers_module.scan(
                rewritten, chosen_language
            ).total
            result.notes.append(
                f"Paraphrased by {chosen_provider} after the offline pass."
            )

        if quiet_text:
            click.echo(result.result, nl=False)
            return

        if as_json:
            import json as json_module

            click.echo(
                json_module.dumps(
                    {**result.to_dict(), "result_text": result.result},
                    indent=2, ensure_ascii=False,
                )
            )
            return

        ctx.out(ui.render_humanize(result))

        if show_diff:
            ctx.out(
                ui.render_diff(
                    run_diff(result.original, result.result, mode="word",
                             label_before="original", label_after="humanized")
                )
            )

        if output:
            _write_output(ctx, output, result.result, "humanized")
        elif not ctx.quiet:
            ctx.console.print(ui.section("RESULT", Text(result.result), style=ui.HUMAN))
    except (LoraError, ProviderError) as error:
        ctx.fail(error)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@cli.command(help="Compare two texts or files.")
@click.argument("before", metavar="BEFORE")
@click.argument("after", metavar="AFTER")
@click.option(
    "--mode", "-m", type=click.Choice(["line", "word", "char"]), default="word",
    show_default=True, help="Comparison granularity.",
)
@click.option(
    "--text", "as_text", is_flag=True,
    help="Treat the arguments as literal text rather than paths.",
)
@click.option("--unified", "-u", is_flag=True, help="Print a unified diff instead.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@pass_context
def diff(ctx, before, after, mode, as_text, unified, as_json):
    try:
        if as_text:
            left, right = before, after
            labels = ("before", "after")
        else:
            left = textio.from_file(before, max_bytes=ctx.config.general.max_bytes).text
            right = textio.from_file(after, max_bytes=ctx.config.general.max_bytes).text
            labels = (before, after)

        result = run_diff(
            left, right, mode=mode, label_before=labels[0], label_after=labels[1]
        )
    except LoraError as error:
        ctx.fail(error)
        return

    if as_json:
        import json as json_module

        click.echo(json_module.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    elif unified:
        click.echo(result.unified or "(no differences)")
    else:
        ctx.out(ui.render_diff(result))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


@cli.command(help="Write a full report as JSON, HTML or Markdown.")
@input_options
@click.option(
    "--format", "fmt", type=click.Choice(sorted(set(FORMATS))), default="json",
    show_default=True, help="Report format.",
)
@click.option("--output", "-o", metavar="PATH", help="Write here instead of stdout.")
@click.option("--include-clean", is_flag=True, help="Also run and include cleaning.")
@click.option(
    "--include-humanize", is_flag=True, help="Also run and include humanization."
)
@click.option("--schema", is_flag=True, help="Print the JSON schema summary and exit.")
@pass_context
def report(
    ctx, text_input, file_input, stdin_flag, fmt, output, include_clean,
    include_humanize, schema,
):
    if schema:
        from ..reports.json_report import schema_info
        import json as json_module

        click.echo(json_module.dumps(schema_info(), indent=2))
        return

    try:
        loaded = _load_input(ctx, text_input, file_input, stdin_flag)
        analysis = run_analysis(loaded)

        clean_result = run_clean(loaded.text, ctx.config.clean.profile) if include_clean else None
        humanize_result = None
        if include_humanize:
            language = loaded.source.language
            humanize_result = run_humanize(
                loaded.text,
                language=language if language in ("en", "ar", "mixed") else "en",
                style=ctx.config.humanize.style,
                intensity=ctx.config.humanize.intensity,
            )

        content = render_report(
            analysis, fmt, clean=clean_result, humanize=humanize_result
        )
        _write_output(ctx, output, content, fmt)
    except LoraError as error:
        ctx.fail(error)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


@cli.command(help="Check that the environment is set up correctly.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a report.")
@pass_context
def doctor(ctx, as_json):
    from .doctor import run_checks, render_checks

    checks = run_checks(ctx.config)

    if as_json:
        import json as json_module

        click.echo(
            json_module.dumps(
                {
                    "checks": [c.to_dict() for c in checks],
                    "healthy": all(c.ok for c in checks if c.required),
                },
                indent=2,
            )
        )
    else:
        ctx.out(render_checks(checks))

    if not all(c.ok for c in checks if c.required):
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@cli.group(help="Inspect and create the configuration file.")
def config():
    pass


@config.command("path", help="Print the config file path.")
def config_path_cmd():
    click.echo(str(config_module.config_path()))


@config.command("show", help="Show the resolved configuration.")
@pass_context
def config_show(ctx):
    import json as json_module

    payload = ctx.config.to_dict()
    payload["_source"] = ctx.config.source_path or "(built-in defaults)"
    click.echo(json_module.dumps(payload, indent=2))


@config.command("init", help="Write a commented default config file.")
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@pass_context
def config_init(ctx, force):
    try:
        path = config_module.write_default(overwrite=force)
    except LoraError as error:
        ctx.fail(error)
        return
    ctx.console.print(
        Text.assemble(("created ", ui.MUTED), (str(path), f"bold {ui.ACCENT}"))
    )


# ---------------------------------------------------------------------------
# tui / version
# ---------------------------------------------------------------------------


@cli.command(help="Open the interactive terminal interface.")
@click.option("--text", "-t", "text_input", help="Pre-load this text.")
@click.option(
    "--file", "-f", "file_input", type=click.Path(dir_okay=False),
    help="Pre-load this file.",
)
@pass_context
def tui(ctx, text_input=None, file_input=None):
    try:
        from ..tui.app import LoraaiApp
    except ImportError as exc:
        ctx.fail(
            LoraError(
                f"The TUI needs Textual, which is not available: {exc}",
                hint="pip install 'loraai-cli' reinstalls the dependencies.",
            )
        )
        return

    initial = ""
    try:
        if file_input:
            initial = textio.from_file(
                file_input, max_bytes=ctx.config.general.max_bytes
            ).text
        elif text_input:
            initial = text_input
        elif textio.stdin_has_data():
            initial = textio.from_stdin(
                max_bytes=ctx.config.general.max_bytes
            ).text
    except LoraError as error:
        ctx.fail(error)
        return

    app = LoraaiApp(config=ctx.config, initial_text=initial, initial_path=file_input)
    app.run()


@cli.command(help="Print version and build details.")
@pass_context
def version(ctx):
    import platform

    ui.banner(ctx.console)
    ctx.console.print(
        ui.section(
            "VERSION",
            ui._kv_table(
                [
                    ("loraai", get_version()),
                    ("Python", platform.python_version()),
                    ("Platform", f"{platform.system()} {platform.release()}"),
                    ("Config", ctx.config.source_path or "(built-in defaults)"),
                ]
            ),
            style=ui.BRAND,
        )
    )


def main() -> None:
    """Console-script entry point."""
    try:
        cli(standalone_mode=False)
    except click.exceptions.Abort:
        raise SystemExit(130)
    except click.exceptions.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code)
    except LoraError as error:
        console = ui.make_console()
        console.stderr = True
        console.print(
            Text.assemble(("error: ", f"bold {ui.SYNTH}"), (error.message,))
        )
        raise SystemExit(error.exit_code)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except BrokenPipeError:  # e.g. `loraai analyze | head`
        try:
            sys.stdout.close()
        finally:
            raise SystemExit(0)


if __name__ == "__main__":  # pragma: no cover
    main()
