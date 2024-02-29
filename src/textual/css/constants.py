from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from typing_extensions import Final

VALID_VISIBILITY: Final = {"visible", "hidden"}
VALID_DISPLAY: Final = {"block", "none"}
VALID_BORDER: Final = {
    "ascii",
    "blank",
    "dashed",
    "double",
    "heavy",
    "hidden",
    "hkey",
    "inner",
    "none",
    "outer",
    "panel",
    "round",
    "solid",
    "tall",
    "thick",
    "vkey",
    "wide",
}
VALID_EDGE: Final = {"top", "right", "bottom", "left"}
VALID_LAYOUT: Final = {"vertical", "horizontal", "grid"}

VALID_BOX_SIZING: Final = {"border-box", "content-box"}
VALID_OVERFLOW: Final = {"scroll", "hidden", "auto"}
VALID_ALIGN_HORIZONTAL: Final = {"left", "center", "right"}
VALID_ALIGN_VERTICAL: Final = {"top", "middle", "bottom"}
VALID_TEXT_ALIGN: Final = {
    "start",
    "end",
    "left",
    "right",
    "center",
    "justify",
}
VALID_SCROLLBAR_GUTTER: Final = {"auto", "stable"}
VALID_STYLE_FLAGS: Final = {
    "b",
    "blink",
    "bold",
    "dim",
    "i",
    "italic",
    "none",
    "not",
    "o",
    "overline",
    "reverse",
    "strike",
    "u",
    "underline",
    "uu",
}
VALID_PSEUDO_CLASSES: Final = {
    "blur",
    "can-focus",
    "dark",
    "disabled",
    "enabled",
    "focus-within",
    "focus",
    "hover",
    "light",
}
VALID_OVERLAY: Final = {"none", "screen"}
VALID_CONSTRAIN: Final = {"x", "y", "both", "inflect", "none"}
VALID_KEYLINE: Final = {"none", "thin", "heavy", "double"}

VALID_RULE_NAMES: Final = {
    "align",
    "align-horizontal",
    "align-vertical",
    "background",
    "border-subtitle-align",
    "border-subtitle-background",
    "border-subtitle-color",
    "border-subtitle-style",
    "border-title-align",
    "border-title-background",
    "border-title-color",
    "border-title-style",
    "border",
    "border-bottom",
    "border-left",
    "border-right",
    "border-top",
    "box-sizing",
    "color",
    "column-span",
    "constrain",
    "content-align",
    "content-align-horizontal",
    "content-align-vertical",
    "display",
    "dock",
    "grid-columns",
    "grid-gutter",
    "grid-rows",
    "grid-size",
    "height",
    "index",
    "keyline",
    "layer",
    "layers",
    "layout",
    "link-background-hover",
    "link-background",
    "link-color-hover",
    "link-color",
    "link-style-hover",
    "link-style",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "offset",
    "offset-x",
    "offset-y",
    "opacity",
    "outline",
    "outline-bottom",
    "outline-left",
    "outline-right",
    "outline-top",
    "overflow",
    "overflow-x",
    "overflow-y",
    "overlay",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "row-span",
    "scrollbar-background-active",
    "scrollbar-background-hover",
    "scrollbar-background",
    "scrollbar-color-active",
    "scrollbar-color-hover",
    "scrollbar-color",
    "scrollbar-corner-color",
    "scrollbar-gutter",
    "scrollbar-size",
    "scrollbar-size-horizontal",
    "scrollbar-size-vertical",
    "text-align",
    "text-opacity",
    "text-style",
    "tint",
    "transition",
    "visibility",
    "width",
}
