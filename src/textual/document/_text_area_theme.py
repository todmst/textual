from __future__ import annotations

from dataclasses import dataclass, field

from rich.style import Style

from textual.app import DEFAULT_COLORS
from textual.color import Color
from textual.design import DEFAULT_DARK_SURFACE


@dataclass
class TextAreaTheme:
    """A theme for the `TextArea` widget.

    Allows theming the general widget (gutter, selections, cursor, and so on) and
    mapping of tree-sitter tokens to Rich styles.

    For example, consider the following snippet from the `markdown.scm` highlight
    query file. We've assigned the `heading_content` token type to the name `heading`.

    ```
    (heading_content) @heading
    ```

    Now, we can map this `heading` name to a Rich style, and it will be styled as
    such in the `TextArea`, assuming a parser which returns a `heading_content`
    node is used (as will be the case when language="markdown").

    ```
    TextAreaTheme('my_theme', token_styles={'heading': Style(color='cyan', bold=True)})
    ```

    We can supply this theme to our `TextArea`, and headings in our markdown files will
    be styled bold cyan.
    """

    name: str | None = None
    """The name of the theme."""

    base_style: Style | None = None
    """The background style of the text area. If `None` the parent style will be used."""

    gutter_style: Style | None = None
    """The style of the gutter. If `None`, a legible TextAreaStyle will be generated."""

    cursor_style: Style | None = None
    """The style of the cursor. If `None`, the legible TextAreaStyle will be generated."""

    cursor_line_style: Style | None = None
    """The style to apply to the line the cursor is on."""

    cursor_line_gutter_style: Style | None = None
    """The style to apply to the gutter of the line the cursor is on. If `None`, a legible Style will be
    generated."""

    bracket_matching_style: Style | None = None
    """The style to apply to matching brackets. If `None`, a legible Style will be generated."""

    selection_style: Style | None = None
    """The style of the selection. If `None` a default selection Style will be generated."""

    token_styles: dict[str, Style] = field(default_factory=dict)
    """The mapping of tree-sitter names from the `highlight_query` to Rich styles."""

    def __post_init__(self) -> None:
        """Generate some styles if they haven't been supplied."""
        if self.base_style is None:
            self.base_style = Style(color="#f3f3f3", bgcolor=DEFAULT_DARK_SURFACE)

        if self.gutter_style is None:
            self.gutter_style = self.base_style.copy()

        background_color = Color.from_rich_color(
            self.base_style.background_style.bgcolor
        )
        if self.cursor_style is None:
            self.cursor_style = Style(
                color=background_color.rich_color,
                bgcolor=background_color.inverse.rich_color,
            )

        if self.cursor_line_gutter_style is None and self.cursor_line_style is not None:
            self.cursor_line_gutter_style = self.cursor_line_style.copy()

        if self.bracket_matching_style is None:
            bracket_matching_background = background_color.blend(
                background_color.inverse, factor=0.05
            )
            self.bracket_matching_style = Style(
                bgcolor=bracket_matching_background.rich_color
            )

        if self.selection_style is None:
            selection_background_color = background_color.blend(
                DEFAULT_COLORS["dark"].primary, factor=0.75
            )
            self.selection_style = Style.from_color(
                bgcolor=selection_background_color.rich_color
            )

    @classmethod
    def get_by_name(cls, theme_name: str) -> "TextAreaTheme":
        """Get a `TextAreaTheme` by name.

        Given a `theme_name` return the corresponding `TextAreaTheme` object.

        Check the available `TextAreaTheme`s by calling `TextAreaTheme.available_themes()`.

        Args:
            theme_name: The name of the theme.

        Returns:
            The `TextAreaTheme` corresponding to the name.
        """
        return _BUILTIN_THEMES.get(theme_name, TextAreaTheme())

    def get_highlight(self, name: str) -> Style:
        """Return the Rich style corresponding to the name defined in the tree-sitter
        highlight query for the current theme.

        Args:
            name: The name of the highlight.

        Returns:
            The `Style` to use for this highlight.
        """
        return self.token_styles.get(name)

    @classmethod
    def available_themes(cls) -> list[TextAreaTheme]:
        """Get a list of all available TextAreaThemes.

        Returns:
            A list of all available TextAreaThemes.
        """
        return list(_BUILTIN_THEMES.values())

    @classmethod
    def default(cls) -> TextAreaTheme:
        """Get the default syntax theme.

        Returns:
            The default TextAreaTheme (probably "monokai").
        """
        return DEFAULT_SYNTAX_THEME


_MONOKAI = TextAreaTheme(
    name="monokai",
    base_style=Style(color="#f8f8f2", bgcolor="#272822"),
    gutter_style=Style(color="#90908a", bgcolor="#272822"),
    cursor_style=Style(color="#272822", bgcolor="#f8f8f0"),
    cursor_line_style=Style(bgcolor="#3e3d32"),
    cursor_line_gutter_style=Style(color="#c2c2bf", bgcolor="#3e3d32"),
    bracket_matching_style=Style(bgcolor="#838889", bold=True),
    selection_style=Style(bgcolor="#65686a"),
    token_styles={
        "string": Style(color="#E6DB74"),
        "string.documentation": Style(color="#E6DB74"),
        "comment": Style(color="#75715E"),
        "keyword": Style(color="#F92672"),
        "operator": Style(color="#F92672"),
        "repeat": Style(color="#F92672"),
        "exception": Style(color="#F92672"),
        "include": Style(color="#F92672"),
        "keyword.function": Style(color="#F92672"),
        "keyword.return": Style(color="#F92672"),
        "keyword.operator": Style(color="#F92672"),
        "conditional": Style(color="#F92672"),
        "number": Style(color="#AE81FF"),
        "float": Style(color="#AE81FF"),
        "class": Style(color="#A6E22E"),
        "type.class": Style(color="#A6E22E"),
        "function": Style(color="#A6E22E"),
        "function.call": Style(color="#A6E22E"),
        "method": Style(color="#A6E22E"),
        "method.call": Style(color="#A6E22E"),
        "boolean": Style(color="#66D9EF", italic=True),
        "json.null": Style(color="#66D9EF", italic=True),
        "regex.punctuation.bracket": Style(color="#F92672"),
        "regex.operator": Style(color="#F92672"),
        "html.end_tag_error": Style(color="red", underline=True),
        "tag": Style(color="#F92672"),
        "yaml.field": Style(color="#F92672", bold=True),
        "json.label": Style(color="#F92672", bold=True),
        "toml.type": Style(color="#F92672"),
        "toml.datetime": Style(color="#AE81FF"),
        "heading": Style(color="#F92672", bold=True),
        "bold": Style(bold=True),
        "italic": Style(italic=True),
        "strikethrough": Style(strike=True),
        "link": Style(color="#66D9EF", underline=True),
        "inline_code": Style(color="#F92672"),
    },
)

_DRACULA = TextAreaTheme(
    name="dracula",
    base_style=Style(color="#f8f8f2", bgcolor="#1E1F35"),
    gutter_style=Style(color="#6272a4"),
    cursor_style=Style(color="#282a36", bgcolor="#f8f8f0"),
    cursor_line_style=Style(bgcolor="#282b45"),
    cursor_line_gutter_style=Style(color="#c2c2bf", bgcolor="#282b45", bold=True),
    bracket_matching_style=Style(bgcolor="#99999d", bold=True, underline=True),
    selection_style=Style(bgcolor="#44475A"),
    token_styles={
        "string": Style(color="#f1fa8c"),
        "string.documentation": Style(color="#f1fa8c"),
        "comment": Style(color="#6272a4"),
        "keyword": Style(color="#ff79c6"),
        "operator": Style(color="#ff79c6"),
        "repeat": Style(color="#ff79c6"),
        "exception": Style(color="#ff79c6"),
        "include": Style(color="#ff79c6"),
        "keyword.function": Style(color="#ff79c6"),
        "keyword.return": Style(color="#ff79c6"),
        "keyword.operator": Style(color="#ff79c6"),
        "conditional": Style(color="#ff79c6"),
        "number": Style(color="#bd93f9"),
        "float": Style(color="#bd93f9"),
        "class": Style(color="#50fa7b"),
        "type.class": Style(color="#50fa7b"),
        "function": Style(color="#50fa7b"),
        "function.call": Style(color="#50fa7b"),
        "method": Style(color="#50fa7b"),
        "method.call": Style(color="#50fa7b"),
        "boolean": Style(color="#bd93f9"),
        "json.null": Style(color="#bd93f9"),
        "regex.punctuation.bracket": Style(color="#ff79c6"),
        "regex.operator": Style(color="#ff79c6"),
        "html.end_tag_error": Style(color="#F83333", underline=True),
        "tag": Style(color="#ff79c6"),
        "yaml.field": Style(color="#ff79c6", bold=True),
        "json.label": Style(color="#ff79c6", bold=True),
        "toml.type": Style(color="#ff79c6"),
        "toml.datetime": Style(color="#bd93f9"),
        "heading": Style(color="#ff79c6", bold=True),
        "bold": Style(bold=True),
        "italic": Style(italic=True),
        "strikethrough": Style(strike=True),
        "link": Style(color="#bd93f9", underline=True),
        "inline_code": Style(color="#ff79c6"),
    },
)

_DARK_VS = TextAreaTheme(
    name="dark_vs",
    base_style=Style(color="#CCCCCC", bgcolor="#1F1F1F"),
    gutter_style=Style(color="#6E7681", bgcolor="#1F1F1F"),
    cursor_style=Style(color="#1e1e1e", bgcolor="#f0f0f0"),
    cursor_line_style=Style(bgcolor="#232323"),
    cursor_line_gutter_style=Style(color="#CCCCCC", bgcolor="#232323"),
    selection_style=Style(bgcolor="#264F78"),
    token_styles={
        "string": Style(color="#ce9178"),
        "string.documentation": Style(color="#ce9178"),
        "comment": Style(color="#6A9955"),
        "keyword": Style(color="#569cd6"),
        "operator": Style(color="#569cd6"),
        "conditional": Style(color="#569cd6"),
        "keyword.function": Style(color="#569cd6"),
        "keyword.return": Style(color="#569cd6"),
        "keyword.operator": Style(color="#d4d4d4"),
        "repeat": Style(color="#569cd6"),
        "exception": Style(color="#569cd6"),
        "include": Style(color="#569cd6"),
        "number": Style(color="#b5cea8"),
        "float": Style(color="#b5cea8"),
        "class": Style(color="#4EC9B0"),
        "type.class": Style(color="#4EC9B0"),
        "function": Style(color="#4EC9B0"),
        "method": Style(color="#4EC9B0"),
        "boolean": Style(color="#7DAF9C"),
        "tag": Style(color="#EFCB43"),
        "yaml.field": Style(color="#EFCB43", bold=True),
        "json.label": Style(color="#EFCB43", bold=True),
        "toml.type": Style(color="#EFCB43"),
        "heading": Style(color="#569cd6", bold=True),
        "bold": Style(bold=True),
        "italic": Style(italic=True),
        "strikethrough": Style(strike=True),
        "link": Style(color="#40A6FF", underline=True),
        "inline_code": Style(color="#ce9178"),
    },
)

_BUILTIN_THEMES = {
    "monokai": _MONOKAI,
    "dracula": _DRACULA,
    "dark_vs": _DARK_VS,
}

DEFAULT_SYNTAX_THEME = TextAreaTheme.get_by_name("monokai")
"""The default syntax highlighting theme used by Textual."""
