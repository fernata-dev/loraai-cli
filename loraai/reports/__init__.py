"""Report writers: JSON for machines, HTML and Markdown for people."""

from . import html_report, json_report, markdown_report

FORMATS = ("json", "html", "markdown", "md")


def render(analysis, fmt: str = "json", **kwargs) -> str:
    """Render *analysis* in the requested format."""
    normalized = fmt.lower()
    if normalized == "json":
        return json_report.dumps(analysis, **kwargs)
    if normalized == "html":
        return html_report.render(analysis, **kwargs)
    if normalized in ("markdown", "md"):
        return markdown_report.render(analysis, **kwargs)
    raise ValueError(
        f"Unknown report format {fmt!r}. Available: {', '.join(FORMATS)}"
    )


__all__ = ["render", "FORMATS", "json_report", "html_report", "markdown_report"]
