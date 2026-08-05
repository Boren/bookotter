"""Filename template engine for library file naming.

Templates are separator-joined token sequences, e.g. the default
``{Author} - {Series} #{SeriesPosition:00} - {Title}``. A token that
resolves to an empty value (book has no series) is dropped together with
the literal separator preceding it, so "Andy Weir - Project Hail Mary"
comes out clean. Literal text after the last token is always kept, which
means wrapping-style templates like ``{Title} ({Series})`` degrade when
the series is absent — separator-joined templates are the supported shape.

Templates govern the filename stem only; directory layout is controlled
by each root folder's folder_organization. Rendered stems must still be
passed through sanitize_path_component before use.
"""

import re

DEFAULT_NAMING_TEMPLATE = "{Author} - {Series} #{SeriesPosition:00} - {Title}"

_TOKEN_RE = re.compile(r"\{(Author|Title|Series|SeriesPosition)(?::(0+))?\}")
_ANY_TOKEN_RE = re.compile(r"\{[^{}]*\}")
_VALID_TOKENS_HINT = "{Author}, {Title}, {Series}, {SeriesPosition} or {SeriesPosition:00}"


def format_series_position(position: float | None, pad: str | None) -> str:
    """Format a series position, zero-padding the integer part to len(pad).

    1 + "00" -> "01"; 1.5 + "00" -> "01.5"; 12 + "00" -> "12"; None -> "".
    Trailing zeros in the fractional part are stripped (2.0 -> "02").
    """
    if position is None:
        return ""
    text = f"{position:g}"
    int_part, _, frac_part = text.partition(".")
    if pad:
        int_part = int_part.zfill(len(pad))
    return f"{int_part}.{frac_part}" if frac_part else int_part


def render_filename(
    template: str,
    *,
    title: str,
    author: str | None,
    series_name: str | None,
    series_position: float | None,
) -> str:
    """Render a filename stem (no extension) from a naming template.

    Empty-valued tokens are dropped along with their preceding literal;
    the first non-empty token keeps the template's leading literal instead
    of its own. Whitespace runs are collapsed afterwards.
    """
    values = {
        "Author": (author or "Unknown Author").strip(),
        "Title": (title or "").strip(),
        "Series": (series_name or "").strip(),
    }

    # re.split with two groups yields [lit0, name, pad, lit1, name, pad, ..., litN]
    parts = _TOKEN_RE.split(template)
    n_tokens = (len(parts) - 1) // 3

    out: list[str] = []
    emitted = False
    for k in range(n_tokens):
        preceding = parts[3 * k]
        name = parts[3 * k + 1]
        pad = parts[3 * k + 2]
        if name == "SeriesPosition":
            value = format_series_position(series_position, pad)
        else:
            value = values[name]
        if not value:
            continue
        out.append(parts[0] if not emitted else preceding)
        out.append(value)
        emitted = True
    out.append(parts[3 * n_tokens])

    return re.sub(r"\s+", " ", "".join(out)).strip()


def validate_template(template: str) -> list[str]:
    """Return a list of human-readable errors; empty list means valid."""
    if not template or not template.strip():
        return ["Template must not be empty."]

    errors: list[str] = []
    if "/" in template or "\\" in template:
        errors.append(
            "Template must not contain path separators ('/' or '\\'); folder layout is configured per root folder."
        )

    known_spans = {m.span() for m in _TOKEN_RE.finditer(template)}
    for m in _ANY_TOKEN_RE.finditer(template):
        if m.span() not in known_spans:
            errors.append(f"Unknown token or bad format spec: {m.group()}. Valid: {_VALID_TOKENS_HINT}.")

    if "{Title}" not in template:
        errors.append("Template must contain {Title}.")

    return errors
