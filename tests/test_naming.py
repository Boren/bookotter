"""Tests for backend.utils.naming — filename template engine."""

from backend.utils.naming import (
    DEFAULT_NAMING_TEMPLATE,
    format_series_position,
    render_filename,
    validate_template,
)


class TestFormatSeriesPosition:
    def test_integer_zero_padded(self):
        assert format_series_position(1, "00") == "01"

    def test_fractional_keeps_fraction(self):
        assert format_series_position(1.5, "00") == "01.5"

    def test_wider_than_pad_unchanged(self):
        assert format_series_position(12, "00") == "12"

    def test_whole_float_renders_as_integer(self):
        assert format_series_position(2.0, "00") == "02"

    def test_no_pad_spec(self):
        assert format_series_position(3, None) == "3"

    def test_no_pad_spec_fractional(self):
        assert format_series_position(1.5, None) == "1.5"

    def test_none_position_is_empty(self):
        assert format_series_position(None, "00") == ""


class TestRenderFilename:
    def test_default_template_full_metadata(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="The Final Empire",
            author="Brandon Sanderson",
            series_name="Mistborn",
            series_position=1,
        )
        assert result == "Brandon Sanderson - Mistborn #01 - The Final Empire"

    def test_fractional_series_position(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="The Eleventh Metal",
            author="Brandon Sanderson",
            series_name="Mistborn",
            series_position=1.5,
        )
        assert result == "Brandon Sanderson - Mistborn #01.5 - The Eleventh Metal"

    def test_no_series_drops_series_segment(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="Project Hail Mary",
            author="Andy Weir",
            series_name=None,
            series_position=None,
        )
        assert result == "Andy Weir - Project Hail Mary"

    def test_series_without_position_drops_position_only(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="The Final Empire",
            author="Brandon Sanderson",
            series_name="Mistborn",
            series_position=None,
        )
        assert result == "Brandon Sanderson - Mistborn - The Final Empire"

    def test_no_author_uses_unknown_author(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="Orphan Book",
            author=None,
            series_name=None,
            series_position=None,
        )
        assert result == "Unknown Author - Orphan Book"

    def test_first_token_empty_uses_template_prefix(self):
        result = render_filename(
            "{Series} - {Title}",
            title="Project Hail Mary",
            author="Andy Weir",
            series_name=None,
            series_position=None,
        )
        assert result == "Project Hail Mary"

    def test_trailing_literal_always_kept(self):
        # Documented limitation: literals after the last token never collapse,
        # so wrapping-style templates misbehave without a series.
        result = render_filename(
            "{Title} ({Series})",
            title="Project Hail Mary",
            author="Andy Weir",
            series_name=None,
            series_position=None,
        )
        assert result == "Project Hail Mary)"

    def test_whitespace_runs_collapsed(self):
        result = render_filename(
            DEFAULT_NAMING_TEMPLATE,
            title="Spaced   Out",
            author="Some  Author",
            series_name=None,
            series_position=None,
        )
        assert result == "Some Author - Spaced Out"


class TestValidateTemplate:
    def test_default_template_valid(self):
        assert validate_template(DEFAULT_NAMING_TEMPLATE) == []

    def test_empty_template_rejected(self):
        assert validate_template("") != []

    def test_whitespace_only_rejected(self):
        assert validate_template("   ") != []

    def test_missing_title_rejected(self):
        errors = validate_template("{Author} - {Series}")
        assert any("Title" in e for e in errors)

    def test_unknown_token_rejected(self):
        errors = validate_template("{Foo} - {Title}")
        assert any("Foo" in e for e in errors)

    def test_bad_format_spec_rejected(self):
        assert validate_template("{SeriesPosition:xx} - {Title}") != []

    def test_forward_slash_rejected(self):
        assert validate_template("{Author}/{Title}") != []

    def test_backslash_rejected(self):
        assert validate_template("{Author}\\{Title}") != []
