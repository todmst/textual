from __future__ import annotations

import functools
from dataclasses import dataclass
from itertools import chain, zip_longest
from operator import itemgetter
from typing import Any, ClassVar, Generic, Iterable, NamedTuple, TypeVar, cast

import rich.repr
from rich.console import RenderableType
from rich.padding import Padding
from rich.protocol import is_renderable
from rich.segment import Segment
from rich.style import Style
from rich.text import Text, TextType
from typing_extensions import Literal, TypeAlias

from .. import events
from .._cache import LRUCache
from .._segment_tools import line_crop
from .._two_way_dict import TwoWayDict
from .._types import SegmentLines
from ..binding import Binding, BindingType
from ..coordinate import Coordinate
from ..geometry import Region, Size, Spacing, clamp
from ..message import Message
from ..reactive import Reactive
from ..render import measure
from ..scroll_view import ScrollView
from ..strip import Strip

CellCacheKey: TypeAlias = "tuple[RowKey, ColumnKey, Style, bool, bool, int]"
LineCacheKey: TypeAlias = (
    "tuple[int, int, int, int, Coordinate, Coordinate, Style, CursorType, bool, int]"
)
RowCacheKey: TypeAlias = (
    "tuple[RowKey, int, Style, Coordinate, Coordinate, CursorType, bool, bool, int]"
)
CursorType = Literal["cell", "row", "column", "none"]
CellType = TypeVar("CellType")


class CellDoesNotExist(Exception):
    """The cell key/index was invalid.

    Raised when the user supplies coordinates or cell keys which
    do not exist in the DataTable."""


class RowDoesNotExist(Exception):
    """Raised when the user supplies a row index or row key which does
    not exist in the DataTable (e.g. out of bounds index, invalid key)"""


class ColumnDoesNotExist(Exception):
    """Raised when the user supplies a column index or column key which does
    not exist in the DataTable (e.g. out of bounds index, invalid key)"""


class DuplicateKey(Exception):
    """The key supplied already exists.

    Raised when the RowKey or ColumnKey provided already refers to
    an existing row or column in the DataTable. Keys must be unique."""


@functools.total_ordering
class StringKey:
    """An object used as a key in a mapping.

    It can optionally wrap a string,
    and lookups into a map using the object behave the same as lookups using
    the string itself."""

    value: str | None

    def __init__(self, value: str | None = None):
        self.value = value

    def __hash__(self):
        # If a string is supplied, we use the hash of the string. If no string was
        # supplied, we use the default hash to ensure uniqueness amongst instances.
        return hash(self.value) if self.value is not None else id(self)

    def __eq__(self, other: object) -> bool:
        # Strings will match Keys containing the same string value.
        # Otherwise, you'll need to supply the exact same key object.
        if isinstance(other, str):
            return self.value == other
        elif isinstance(other, StringKey):
            if self.value is not None and other.value is not None:
                return self.value == other.value
            else:
                return hash(self) == hash(other)
        else:
            raise NotImplemented

    def __lt__(self, other):
        if isinstance(other, str):
            return self.value < other
        elif isinstance(other, StringKey):
            return self.value < other.value
        else:
            raise NotImplemented

    def __rich_repr__(self):
        yield "value", self.value


class RowKey(StringKey):
    """Uniquely identifies a row in the DataTable.

    Even if the visual location
    of the row changes due to sorting or other modifications, a key will always
    refer to the same row."""


class ColumnKey(StringKey):
    """Uniquely identifies a column in the DataTable.

    Even if the visual location
    of the column changes due to sorting or other modifications, a key will always
    refer to the same column."""


class CellKey(NamedTuple):
    """A unique identifier for a cell in the DataTable.

    Even if the cell changes
    visual location (i.e. moves to a different coordinate in the table), this key
    can still be used to retrieve it, regardless of where it currently is."""

    row_key: RowKey
    column_key: ColumnKey

    def __rich_repr__(self):
        yield "row_key", self.row_key
        yield "column_key", self.column_key


def default_cell_formatter(obj: object) -> RenderableType:
    """Convert a cell into a Rich renderable for display.

    Args:
        obj: Data for a cell.

    Returns:
        A renderable to be displayed which represents the data.
    """
    if isinstance(obj, str):
        return Text.from_markup(obj)
    if isinstance(obj, float):
        return f"{obj:.2f}"
    if not is_renderable(obj):
        return str(obj)
    return cast(RenderableType, obj)


@dataclass
class Column:
    """Metadata for a column in the DataTable."""

    key: ColumnKey
    label: Text
    width: int = 0
    content_width: int = 0
    auto_width: bool = False

    @property
    def render_width(self) -> int:
        """Width in cells, required to render a column."""
        # +2 is to account for space padding either side of the cell
        if self.auto_width:
            return self.content_width + 2
        else:
            return self.width + 2


@dataclass
class Row:
    """Metadata for a row in the DataTable."""

    key: RowKey
    height: int
    label: str | None = None


class RenderedRow(NamedTuple):
    """Container for a row, which contains an optional label and some data cells."""

    label: RenderableType | None
    cells: list[RenderableType]


class DataTable(ScrollView, Generic[CellType], can_focus=True):
    """A tabular widget that contains data."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_cursor", "Select", show=False),
        Binding("up", "cursor_up", "Cursor Up", show=False),
        Binding("down", "cursor_down", "Cursor Down", show=False),
        Binding("right", "cursor_right", "Cursor Right", show=False),
        Binding("left", "cursor_left", "Cursor Left", show=False),
    ]
    """
    | Key(s) | Description |
    | :- | :- |
    | enter | Select cells under the cursor. |
    | up | Move the cursor up. |
    | down | Move the cursor down. |
    | right | Move the cursor right. |
    | left | Move the cursor left. |
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "datatable--cursor",
        "datatable--hover",
        "datatable--fixed",
        "datatable--header",
        "datatable--header-cursor",
        "datatable--header-hover",
        "datatable--fixed-cursor",
        "datatable--odd-row",
        "datatable--even-row",
    }
    """
    | Class | Description |
    | :- | :- |
    | `datatable--cursor` | Target the cursor. |
    | `datatable--header-cursor` | Target fixed columns or header under the cursor. |
    | `datatable--even-row` | Target even rows (row indices start at 0). |
    | `datatable--fixed` | Target fixed columns or header. |
    | `datatable--header` | Target the header of the data table. |
    | `datatable--hover` | Target the highlighted cell(s). |
    | `datatable--header-hover` | Target highlighted and fixed columns or header. |
    | `datatable--odd-row` | Target odd rows (row indices start at 0). |
    """

    DEFAULT_CSS = """
    App.-dark DataTable {
        background:;
    }
    DataTable {
        background: $surface ;
        color: $text;
    }
    DataTable > .datatable--header {
        text-style: bold;
        background: $primary;
        color: $text;
    }
    DataTable > .datatable--fixed {
        background: $primary 50%;
        color: $text;
    }

    DataTable > .datatable--odd-row {

    }

    DataTable > .datatable--even-row {
        background: $primary 10%;
    }

    DataTable >  .datatable--cursor {
        background: $secondary;
        color: $text;
    }

    DataTable > .datatable--fixed-cursor {
        background: $secondary 92%;
        color: $text;
    }

    DataTable > .datatable--header-cursor {
        background: $secondary-darken-1;
        color: $text;
    }

    DataTable > .datatable--header-hover {
        background: $secondary 30%;
    }

    .-dark-mode DataTable > .datatable--even-row {
        background: $primary 15%;
    }

    DataTable > .datatable--hover {
        background: $secondary 20%;
    }
    """

    show_header = Reactive(True)
    show_row_labels = Reactive(True)
    fixed_rows = Reactive(0)
    fixed_columns = Reactive(0)
    zebra_stripes = Reactive(False)
    header_height = Reactive(1)
    show_cursor = Reactive(True)
    cursor_type = Reactive("cell")

    cursor_coordinate: Reactive[Coordinate] = Reactive(
        Coordinate(0, 0), repaint=False, always_update=True
    )
    hover_coordinate: Reactive[Coordinate] = Reactive(Coordinate(0, 0), repaint=False)

    class CellHighlighted(Message, bubble=True):
        """Posted when the cursor moves to highlight a new cell.

        This is only relevant when the `cursor_type` is `"cell"`.
        It's also posted when the cell cursor is
        re-enabled (by setting `show_cursor=True`), and when the cursor type is
        changed to `"cell"`. Can be handled using `on_data_table_cell_highlighted` in
        a subclass of `DataTable` or in a parent widget in the DOM.
        """

        def __init__(
            self,
            sender: DataTable,
            value: CellType,
            coordinate: Coordinate,
            cell_key: CellKey,
        ) -> None:
            self.value: CellType = value
            """The value in the highlighted cell."""
            self.coordinate: Coordinate = coordinate
            """The coordinate of the highlighted cell."""
            self.cell_key: CellKey = cell_key
            """The key for the highlighted cell."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "value", self.value
            yield "coordinate", self.coordinate
            yield "cell_key", self.cell_key

    class CellSelected(Message, bubble=True):
        """Posted by the `DataTable` widget when a cell is selected.

        This is only relevant when the `cursor_type` is `"cell"`. Can be handled using
        `on_data_table_cell_selected` in a subclass of `DataTable` or in a parent
        widget in the DOM.
        """

        def __init__(
            self,
            sender: DataTable,
            value: CellType,
            coordinate: Coordinate,
            cell_key: CellKey,
        ) -> None:
            self.value: CellType = value
            """The value in the cell that was selected."""
            self.coordinate: Coordinate = coordinate
            """The coordinate of the cell that was selected."""
            self.cell_key: CellKey = cell_key
            """The key for the selected cell."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "value", self.value
            yield "coordinate", self.coordinate
            yield "cell_key", self.cell_key

    class RowHighlighted(Message, bubble=True):
        """Posted when a row is highlighted.

        This message is only posted when the
        `cursor_type` is set to `"row"`. Can be handled using
        `on_data_table_row_highlighted` in a subclass of `DataTable` or in a parent
        widget in the DOM.
        """

        def __init__(self, sender: DataTable, cursor_row: int, row_key: RowKey) -> None:
            self.cursor_row: int = cursor_row
            """The y-coordinate of the cursor that highlighted the row."""
            self.row_key: RowKey = row_key
            """The key of the row that was highlighted."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "cursor_row", self.cursor_row
            yield "row_key", self.row_key

    class RowSelected(Message, bubble=True):
        """Posted when a row is selected.

        This message is only posted when the
        `cursor_type` is set to `"row"`. Can be handled using
        `on_data_table_row_selected` in a subclass of `DataTable` or in a parent
        widget in the DOM.
        """

        def __init__(self, sender: DataTable, cursor_row: int, row_key: RowKey) -> None:
            self.cursor_row: int = cursor_row
            """The y-coordinate of the cursor that made the selection."""
            self.row_key: RowKey = row_key
            """The key of the row that was selected."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "cursor_row", self.cursor_row
            yield "row_key", self.row_key

    class ColumnHighlighted(Message, bubble=True):
        """Posted when a column is highlighted.

        This message is only posted when the
        `cursor_type` is set to `"column"`. Can be handled using
        `on_data_table_column_highlighted` in a subclass of `DataTable` or in a parent
        widget in the DOM.
        """

        def __init__(
            self, sender: DataTable, cursor_column: int, column_key: ColumnKey
        ) -> None:
            self.cursor_column: int = cursor_column
            """The x-coordinate of the column that was highlighted."""
            self.column_key = column_key
            """The key of the column that was highlighted."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "cursor_column", self.cursor_column
            yield "column_key", self.column_key

    class ColumnSelected(Message, bubble=True):
        """Posted when a column is selected.

        This message is only posted when the
        `cursor_type` is set to `"column"`. Can be handled using
        `on_data_table_column_selected` in a subclass of `DataTable` or in a parent
        widget in the DOM.
        """

        def __init__(
            self, sender: DataTable, cursor_column: int, column_key: ColumnKey
        ) -> None:
            self.cursor_column: int = cursor_column
            """The x-coordinate of the column that was selected."""
            self.column_key = column_key
            """The key of the column that was selected."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "cursor_column", self.cursor_column
            yield "column_key", self.column_key

    class HeaderSelected(Message, bubble=True):
        """Posted when a column header/label is clicked."""

        def __init__(
            self,
            sender: DataTable,
            column_key: ColumnKey,
            column_index: int,
            label: Text,
        ):
            self.column_key = column_key
            """The key for the column."""
            self.column_index = column_index
            """The index for the column."""
            self.label = label
            """The text of the label."""
            super().__init__(sender)

        def __rich_repr__(self) -> rich.repr.Result:
            yield "sender", self.sender
            yield "column_key", self.column_key
            yield "label", self.label.plain

    def __init__(
        self,
        *,
        show_header: bool = True,
        show_row_labels: bool = True,
        fixed_rows: int = 0,
        fixed_columns: int = 0,
        zebra_stripes: bool = False,
        header_height: int = 1,
        show_cursor: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._data: dict[RowKey, dict[ColumnKey, CellType]] = {}
        """Contains the cells of the table, indexed by row key and column key.
        The final positioning of a cell on screen cannot be determined solely by this
        structure. Instead, we must check _row_locations and _column_locations to find
        where each cell currently resides in space."""

        self.columns: dict[ColumnKey, Column] = {}
        """Metadata about the columns of the table, indexed by their key."""
        self.rows: dict[RowKey, Row] = {}
        """Metadata about the rows of the table, indexed by their key."""

        # Keep tracking of key -> index for rows/cols. These allow us to retrieve,
        # given a row or column key, the index that row or column is currently
        # present at, and mean that rows and columns are location independent - they
        # can move around without requiring us to modify the underlying data.
        self._row_locations: TwoWayDict[RowKey, int] = TwoWayDict({})
        """Maps row keys to row indices which represent row order."""
        self._column_locations: TwoWayDict[ColumnKey, int] = TwoWayDict({})
        """Maps column keys to column indices which represent column order."""

        self._row_render_cache: LRUCache[
            RowCacheKey, tuple[SegmentLines, SegmentLines]
        ] = LRUCache(1000)
        """For each row (a row can have a height of multiple lines), we maintain a
        cache of the fixed and scrollable lines within that row to minimise how often
        we need to re-render it. """
        self._cell_render_cache: LRUCache[CellCacheKey, SegmentLines] = LRUCache(10000)
        """Cache for individual cells."""
        self._line_cache: LRUCache[LineCacheKey, Strip] = LRUCache(1000)
        """Cache for lines within rows."""
        self._offset_cache: LRUCache[int, list[tuple[RowKey, int]]] = LRUCache(1)
        """Cached y_offset - key is update_count - see y_offsets property for more
        information """
        self._ordered_row_cache: LRUCache[tuple[int, int], list[Row]] = LRUCache(1)
        """Caches row ordering - key is (num_rows, update_count)."""

        self._require_update_dimensions: bool = False
        """Set to re-calculate dimensions on idle."""
        self._new_rows: set[RowKey] = set()
        """Tracking newly added rows to be used in calculation of dimensions on idle."""
        self._updated_cells: set[CellKey] = set()
        """Track which cells were updated, so that we can refresh them once on idle."""

        self._show_hover_cursor = False
        """Used to hide the mouse hover cursor when the user uses the keyboard."""
        self._update_count = 0
        """Number of update (INCLUDING SORT) operations so far. Used for cache invalidation."""
        self._header_row_key = RowKey()
        """The header is a special row - not part of the data. Retrieve via this key."""
        self._label_column_key = ColumnKey()
        """The column containing row labels is not part of the data. This key identifies it."""
        self._labelled_row_exists = False
        """Whether or not the user has supplied any rows with labels."""
        self._row_label_column_width = 0

        self.show_header = show_header
        """Show/hide the header row (the row of column labels)."""
        self.show_row_labels = show_row_labels
        """Show/hide the column containing the labels of rows."""
        self.header_height = header_height
        """The height of the header row (the row of column labels)."""
        self.fixed_rows = fixed_rows
        """The number of rows to fix (prevented from scrolling)."""
        self.fixed_columns = fixed_columns
        """The number of columns to fix (prevented from scrolling)."""
        self.zebra_stripes = zebra_stripes
        """Apply zebra effect on row backgrounds (light, dark, light, dark, ...)."""
        self.show_cursor = show_cursor
        """Show/hide both the keyboard and hover cursor."""

    @property
    def hover_row(self) -> int:
        """The index of the row that the mouse cursor is currently hovering above."""
        return self.hover_coordinate.row

    @property
    def hover_column(self) -> int:
        """The index of the column that the mouse cursor is currently hovering above."""
        return self.hover_coordinate.column

    @property
    def cursor_row(self) -> int:
        """The index of the row that the DataTable cursor is currently on."""
        return self.cursor_coordinate.row

    @property
    def cursor_column(self) -> int:
        """The index of the column that the DataTable cursor is currently on."""
        return self.cursor_coordinate.column

    @property
    def row_count(self) -> int:
        """The number of rows currently present in the DataTable."""
        return len(self.rows)

    @property
    def _y_offsets(self) -> list[tuple[RowKey, int]]:
        """Contains a 2-tuple for each line (not row!) of the DataTable. Given a
        y-coordinate, we can index into this list to find which row that y-coordinate
        lands on, and the y-offset *within* that row. The length of the returned list
        is therefore the total height of all rows within the DataTable."""
        y_offsets = []
        if self._update_count in self._offset_cache:
            y_offsets = self._offset_cache[self._update_count]
        else:
            for row in self.ordered_rows:
                y_offsets += [(row.key, y) for y in range(row.height)]
            self._offset_cache[self._update_count] = y_offsets
        return y_offsets

    @property
    def _total_row_height(self) -> int:
        """The total height of all rows within the DataTable"""
        return len(self._y_offsets)

    def update_cell(
        self,
        row_key: RowKey | str,
        column_key: ColumnKey | str,
        value: CellType,
        *,
        update_width: bool = False,
    ) -> None:
        """Update the cell identified by the specified row key and column key.

        Args:
            row_key: The key identifying the row.
            column_key: The key identifying the column.
            value: The new value to put inside the cell.
            update_width: Whether to resize the column width to accommodate
                for the new cell content.

        Raises:
            CellDoesNotExist: When the supplied `row_key` and `column_key`
                cannot be found in the table.
        """
        if isinstance(row_key, str):
            row_key = RowKey(row_key)
        if isinstance(column_key, str):
            column_key = ColumnKey(column_key)

        try:
            self._data[row_key][column_key] = value
        except KeyError:
            raise CellDoesNotExist(
                f"No cell exists for row_key={row_key!r}, column_key={column_key!r}."
            ) from None
        self._update_count += 1

        # Recalculate widths if necessary
        if update_width:
            self._updated_cells.add(CellKey(row_key, column_key))
            self._require_update_dimensions = True

        self.refresh()

    def update_cell_at(
        self, coordinate: Coordinate, value: CellType, *, update_width: bool = False
    ) -> None:
        """Update the content inside the cell currently occupying the given coordinate.

        Args:
            coordinate: The coordinate to update the cell at.
            value: The new value to place inside the cell.
            update_width: Whether to resize the column width to accommodate
                for the new cell content.
        """
        if not self.is_valid_coordinate(coordinate):
            raise CellDoesNotExist(f"Coordinate {coordinate!r} is invalid.")

        row_key, column_key = self.coordinate_to_cell_key(coordinate)
        self.update_cell(row_key, column_key, value, update_width=update_width)

    def get_cell(self, row_key: RowKey, column_key: ColumnKey) -> CellType:
        """Given a row key and column key, return the value of the corresponding cell.

        Args:
            row_key: The row key of the cell.
            column_key: The column key of the cell.

        Returns:
            The value of the cell identified by the row and column keys.
        """
        try:
            cell_value = self._data[row_key][column_key]
        except KeyError:
            raise CellDoesNotExist(
                f"No cell exists for row_key={row_key!r}, column_key={column_key!r}."
            )
        return cell_value

    def get_cell_at(self, coordinate: Coordinate) -> CellType:
        """Get the value from the cell occupying the given coordinate.

        Args:
            coordinate: The coordinate to retrieve the value from.

        Returns:
            The value of the cell at the coordinate.

        Raises:
            CellDoesNotExist: If there is no cell with the given coordinate.
        """
        row_key, column_key = self.coordinate_to_cell_key(coordinate)
        return self.get_cell(row_key, column_key)

    def get_row(self, row_key: RowKey | str) -> list[CellType]:
        """Get the values from the row identified by the given row key.

        Args:
            row_key: The key of the row.

        Returns:
            A list of the values contained within the row.

        Raises:
            RowDoesNotExist: When there is no row corresponding to the key.
        """
        if row_key not in self._row_locations:
            raise RowDoesNotExist(f"Row key {row_key!r} is not valid.")
        cell_mapping: dict[ColumnKey, CellType] = self._data.get(row_key, {})
        ordered_row: list[CellType] = [
            cell_mapping[column.key] for column in self.ordered_columns
        ]
        return ordered_row

    def get_row_at(self, row_index: int) -> list[CellType]:
        """Get the values from the cells in a row at a given index. This will
        return the values from a row based on the rows _current position_ in
        the table.

        Args:
            row_index: The index of the row.

        Returns:
            A list of the values contained in the row.

        Raises:
            RowDoesNotExist: If there is no row with the given index.
        """
        if not self.is_valid_row_index(row_index):
            raise RowDoesNotExist(f"Row index {row_index!r} is not valid.")
        row_key = self._row_locations.get_key(row_index)
        return self.get_row(row_key)

    def get_column(self, column_key: ColumnKey | str) -> Iterable[CellType]:
        """Get the values from the column identified by the given column key.

        Args:
            column_key: The key of the column.

        Returns:
            A generator which yields the cells in the column.

        Raises:
            ColumnDoesNotExist: If there is no column corresponding to the key.
        """
        if column_key not in self._column_locations:
            raise ColumnDoesNotExist(f"Column key {column_key!r} is not valid.")

        data = self._data
        for row_metadata in self.ordered_rows:
            row_key = row_metadata.key
            yield data[row_key][column_key]

    def get_column_at(self, column_index: int) -> Iterable[CellType]:
        """Get the values from the column at a given index.

        Args:
            column_index: The index of the column.

        Returns:
            A generator which yields the cells in the column.

        Raises:
            ColumnDoesNotExist: If there is no column with the given index.
        """
        if not self.is_valid_column_index(column_index):
            raise ColumnDoesNotExist(f"Column index {column_index!r} is not valid.")

        column_key = self._column_locations.get_key(column_index)
        yield from self.get_column(column_key)

    def _clear_caches(self) -> None:
        self._row_render_cache.clear()
        self._cell_render_cache.clear()
        self._line_cache.clear()
        self._styles_cache.clear()
        self._offset_cache.clear()
        self._ordered_row_cache.clear()

    def get_row_height(self, row_key: RowKey) -> int:
        """Given a row key, return the height of that row in terminal cells.

        Args:
            row_key: The key of the row.

        Returns:
            The height of the row, measured in terminal character cells.
        """
        if row_key is self._header_row_key:
            return self.header_height
        return self.rows[row_key].height

    async def on_styles_updated(self) -> None:
        self._clear_caches()
        self.refresh()

    def watch_show_cursor(self, show_cursor: bool) -> None:
        self._clear_caches()
        if show_cursor and self.cursor_type != "none":
            # When we re-enable the cursor, apply highlighting and
            # post the appropriate [Row|Column|Cell]Highlighted event.
            self._scroll_cursor_into_view(animate=False)
            if self.cursor_type == "cell":
                self._highlight_coordinate(self.cursor_coordinate)
            elif self.cursor_type == "row":
                self._highlight_row(self.cursor_row)
            elif self.cursor_type == "column":
                self._highlight_column(self.cursor_column)

    def watch_show_header(self, show: bool) -> None:
        width, height = self.virtual_size
        height_change = self.header_height if show else -self.header_height
        self.virtual_size = Size(width, height + height_change)
        self._scroll_cursor_into_view()
        self._clear_caches()

    def watch_fixed_rows(self) -> None:
        self._clear_caches()

    def watch_fixed_columns(self) -> None:
        self._clear_caches()

    def watch_zebra_stripes(self) -> None:
        self._clear_caches()

    def watch_hover_coordinate(self, old: Coordinate, value: Coordinate) -> None:
        self.refresh_coordinate(old)
        self.refresh_coordinate(value)

    def watch_cursor_coordinate(
        self, old_coordinate: Coordinate, new_coordinate: Coordinate
    ) -> None:
        if old_coordinate != new_coordinate:
            # Refresh the old and the new cell, and post the appropriate
            # message to tell users of the newly highlighted row/cell/column.
            if self.cursor_type == "cell":
                self.refresh_coordinate(old_coordinate)
                self._highlight_coordinate(new_coordinate)
            elif self.cursor_type == "row":
                self.refresh_row(old_coordinate.row)
                self._highlight_row(new_coordinate.row)
            elif self.cursor_type == "column":
                self.refresh_column(old_coordinate.column)
                self._highlight_column(new_coordinate.column)

    def _highlight_coordinate(self, coordinate: Coordinate) -> None:
        """Apply highlighting to the cell at the coordinate, and post event."""
        self.refresh_coordinate(coordinate)
        try:
            cell_value = self.get_cell_at(coordinate)
        except CellDoesNotExist:
            # The cell may not exist e.g. when the table is cleared.
            # In that case, there's nothing for us to do here.
            return
        else:
            cell_key = self.coordinate_to_cell_key(coordinate)
            self.post_message_no_wait(
                DataTable.CellHighlighted(
                    self, cell_value, coordinate=coordinate, cell_key=cell_key
                )
            )

    def coordinate_to_cell_key(self, coordinate: Coordinate) -> CellKey:
        """Return the key for the cell currently occupying this coordinate.

        Args:
            coordinate: The coordinate to exam the current cell key of.

        Returns:
            The key of the cell currently occupying this coordinate.

        Raises:
            CellDoesNotExist: If the coordinate is not valid.
        """
        if not self.is_valid_coordinate(coordinate):
            raise CellDoesNotExist(f"No cell exists at {coordinate!r}.")
        row_index, column_index = coordinate
        row_key = self._row_locations.get_key(row_index)
        column_key = self._column_locations.get_key(column_index)
        return CellKey(row_key, column_key)

    def _highlight_row(self, row_index: int) -> None:
        """Apply highlighting to the row at the given index, and post event."""
        self.refresh_row(row_index)
        is_valid_row = row_index < len(self._data)
        if is_valid_row:
            row_key = self._row_locations.get_key(row_index)
            self.post_message_no_wait(
                DataTable.RowHighlighted(self, row_index, row_key)
            )

    def _highlight_column(self, column_index: int) -> None:
        """Apply highlighting to the column at the given index, and post event."""
        self.refresh_column(column_index)
        if column_index < len(self.columns):
            column_key = self._column_locations.get_key(column_index)
            self.post_message_no_wait(
                DataTable.ColumnHighlighted(self, column_index, column_key)
            )

    def validate_cursor_coordinate(self, value: Coordinate) -> Coordinate:
        return self._clamp_cursor_coordinate(value)

    def _clamp_cursor_coordinate(self, coordinate: Coordinate) -> Coordinate:
        """Clamp a coordinate such that it falls within the boundaries of the table."""
        row, column = coordinate
        row = clamp(row, 0, self.row_count - 1)
        column = clamp(column, 0, len(self.columns) - 1)
        return Coordinate(row, column)

    def watch_cursor_type(self, old: str, new: str) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor:
            self._highlight_cursor()

        # Refresh cells that were previously impacted by the cursor
        # but may no longer be.
        if old == "cell":
            self.refresh_coordinate(self.cursor_coordinate)
        elif old == "row":
            row_index, _ = self.cursor_coordinate
            self.refresh_row(row_index)
        elif old == "column":
            _, column_index = self.cursor_coordinate
            self.refresh_column(column_index)

        self._scroll_cursor_into_view()

    def _highlight_cursor(self) -> None:
        """Applies the appropriate highlighting and raises the appropriate
        [Row|Column|Cell]Highlighted event for the given cursor coordinate
        and cursor type."""
        row_index, column_index = self.cursor_coordinate
        cursor_type = self.cursor_type
        # Apply the highlighting to the newly relevant cells
        if cursor_type == "cell":
            self._highlight_coordinate(self.cursor_coordinate)
        elif cursor_type == "row":
            self._highlight_row(row_index)
        elif cursor_type == "column":
            self._highlight_column(column_index)

    def _update_column_widths(self, updated_cells: set[CellKey]) -> None:
        """Update the widths of the columns based on the newly updated cell widths."""
        for row_key, column_key in updated_cells:
            column = self.columns.get(column_key)
            if column is None:
                continue
            console = self.app.console
            label_width = measure(console, column.label, 1)
            content_width = column.content_width
            cell_value = self._data[row_key][column_key]

            new_content_width = measure(console, default_cell_formatter(cell_value), 1)

            if new_content_width < content_width:
                cells_in_column = self.get_column(column_key)
                cell_widths = [
                    measure(console, default_cell_formatter(cell), 1)
                    for cell in cells_in_column
                ]
                column.content_width = max([*cell_widths, label_width])
            else:
                column.content_width = max(new_content_width, label_width)

    def _update_dimensions(self, new_rows: Iterable[RowKey]) -> None:
        """Called to recalculate the virtual (scrollable) size."""
        for row_key in new_rows:
            row_index = self._row_locations.get(row_key)
            row = self.rows.get(row_key)
            if row.label is not None:
                self._labelled_row_exists = True

            # self._row_label_column_width = max(self._row_label_column_width, )
            if row_index is None:
                continue
            for column, renderable in zip(
                self.ordered_columns, self._get_row_renderables(row_index).cells
            ):
                content_width = measure(self.app.console, renderable, 1)
                column.content_width = max(column.content_width, content_width)

        self._clear_caches()
        total_width = sum(column.render_width for column in self.columns.values())
        header_height = self.header_height if self.show_header else 0
        self.virtual_size = Size(
            total_width,
            self._total_row_height + header_height,
        )

    def _get_cell_region(self, coordinate: Coordinate) -> Region:
        """Get the region of the cell at the given spatial coordinate."""
        if not self.is_valid_coordinate(coordinate):
            return Region(0, 0, 0, 0)

        row_index, column_index = coordinate
        row_key = self._row_locations.get_key(row_index)
        row = self.rows[row_key]

        # The x-coordinate of a cell is the sum of widths of cells to the left.
        x = sum(column.render_width for column in self.ordered_columns[:column_index])
        column_key = self._column_locations.get_key(column_index)
        width = self.columns[column_key].render_width
        height = row.height
        y = sum(ordered_row.height for ordered_row in self.ordered_rows[:row_index])
        if self.show_header:
            y += self.header_height
        cell_region = Region(x, y, width, height)
        return cell_region

    def _get_row_region(self, row_index: int) -> Region:
        """Get the region of the row at the given index."""
        if not self.is_valid_row_index(row_index):
            return Region(0, 0, 0, 0)

        rows = self.rows
        row_key = self._row_locations.get_key(row_index)
        row = rows[row_key]
        row_width = sum(column.render_width for column in self.columns.values())
        y = sum(ordered_row.height for ordered_row in self.ordered_rows[:row_index])
        if self.show_header:
            y += self.header_height
        row_region = Region(0, y, row_width, row.height)
        return row_region

    def _get_column_region(self, column_index: int) -> Region:
        """Get the region of the column at the given index."""
        if not self.is_valid_column_index(column_index):
            return Region(0, 0, 0, 0)

        columns = self.columns
        x = sum(column.render_width for column in self.ordered_columns[:column_index])
        column_key = self._column_locations.get_key(column_index)
        width = columns[column_key].render_width
        header_height = self.header_height if self.show_header else 0
        height = self._total_row_height + header_height
        full_column_region = Region(x, 0, width, height)
        return full_column_region

    def clear(self, columns: bool = False) -> None:
        """Clear the table.

        Args:
            columns: Also clear the columns. Defaults to False.
        """
        self._clear_caches()
        self._y_offsets.clear()
        self._data.clear()
        self.rows.clear()
        self._row_locations = TwoWayDict({})
        if columns:
            self.columns.clear()
            self._column_locations = TwoWayDict({})
        self._require_update_dimensions = True
        self.cursor_coordinate = Coordinate(0, 0)
        self.hover_coordinate = Coordinate(0, 0)
        self._labelled_row_exists = False
        self.refresh()

    def add_column(
        self, label: TextType, *, width: int | None = None, key: str | None = None
    ) -> ColumnKey:
        """Add a column to the table.

        Args:
            label: A str or Text object containing the label (shown top of column).
            width: Width of the column in cells or None to fit content.
            key: A key which uniquely identifies this column.
                If None, it will be generated for you.

        Returns:
            Uniquely identifies this column. Can be used to retrieve this column
                regardless of its current location in the DataTable (it could have moved
                after being added due to sorting/insertion/deletion of other columns).
        """
        column_key = ColumnKey(key)
        if column_key in self._column_locations:
            raise DuplicateKey(f"The column key {key!r} already exists.")
        column_index = len(self.columns)
        label = Text.from_markup(label) if isinstance(label, str) else label
        content_width = measure(self.app.console, label, 1)
        if width is None:
            column = Column(
                column_key,
                label,
                content_width,
                content_width=content_width,
                auto_width=True,
            )
        else:
            column = Column(
                column_key,
                label,
                width,
                content_width=content_width,
            )

        self.columns[column_key] = column
        self._column_locations[column_key] = column_index
        self._require_update_dimensions = True
        self.check_idle()

        return column_key

    def add_row(
        self,
        *cells: CellType,
        height: int = 1,
        key: str | None = None,
        label: str | None = None,
    ) -> RowKey:
        """Add a row at the bottom of the DataTable.

        Args:
            *cells: Positional arguments should contain cell data.
            height: The height of a row (in lines).
            key: A key which uniquely identifies this row. If None, it will be generated
                for you and returned.
            label: The label for the row. Will be displayed to the left if supplied.

        Returns:
            Uniquely identifies this row. Can be used to retrieve this row regardless
                of its current location in the DataTable (it could have moved after
                being added due to sorting or insertion/deletion of other rows).
        """
        row_key = RowKey(key)
        if row_key in self._row_locations:
            raise DuplicateKey(f"The row key {row_key!r} already exists.")

        # TODO: If there are no columns: do we generate them here?
        #  If we don't do this, users will be required to call add_column(s)
        #  Before they call add_row.

        row_index = self.row_count
        # Map the key of this row to its current index
        self._row_locations[row_key] = row_index
        self._data[row_key] = {
            column.key: cell
            for column, cell in zip_longest(self.ordered_columns, cells)
        }
        self.rows[row_key] = Row(row_key, height, label)
        self._new_rows.add(row_key)
        self._require_update_dimensions = True
        self.cursor_coordinate = self.cursor_coordinate

        # If a position has opened for the cursor to appear, where it previously
        # could not (e.g. when there's no data in the table), then a highlighted
        # event is posted, since there's now a highlighted cell when there wasn't
        # before.
        cell_now_available = self.row_count == 1 and len(self.columns) > 0
        visible_cursor = self.show_cursor and self.cursor_type != "none"
        if cell_now_available and visible_cursor:
            self._highlight_cursor()

        self._update_count += 1
        self.check_idle()
        return row_key

    def add_columns(self, *labels: TextType) -> list[ColumnKey]:
        """Add a number of columns.

        Args:
            *labels: Column headers.

        Returns:
            A list of the keys for the columns that were added. See
                the `add_column` method docstring for more information on how
                these keys are used.
        """
        column_keys = []
        for label in labels:
            column_key = self.add_column(label, width=None)
            column_keys.append(column_key)
        return column_keys

    def add_rows(self, rows: Iterable[Iterable[CellType]]) -> list[RowKey]:
        """Add a number of rows at the bottom of the DataTable.

        Args:
            rows: Iterable of rows. A row is an iterable of cells.

        Returns:
            A list of the keys for the rows that were added. See
                the `add_row` method docstring for more information on how
                these keys are used.
        """
        row_keys = []
        for row in rows:
            row_key = self.add_row(*row)
            row_keys.append(row_key)
        return row_keys

    def on_idle(self) -> None:
        """Runs when the message pump is empty.

        We use this for some expensive calculations like re-computing dimensions of the
        whole DataTable and re-computing column widths after some cells
        have been updated. This is more efficient in the case of high
        frequency updates, ensuring we only do expensive computations once."""
        if self._require_update_dimensions:
            # Add the new rows *before* updating the column widths, since
            # cells in a new row may influence the final width of a column
            self._require_update_dimensions = False
            new_rows = self._new_rows.copy()
            self._new_rows.clear()
            self._update_dimensions(new_rows)

        if self._updated_cells:
            # Cell contents have already been updated at this point.
            # Now we only need to worry about measuring column widths.
            updated_columns = self._updated_cells.copy()
            self._updated_cells.clear()
            self._update_column_widths(updated_columns)

    def refresh_coordinate(self, coordinate: Coordinate) -> None:
        """Refresh the cell at a coordinate.

        Args:
            coordinate: The coordinate to refresh.
        """
        if not self.is_valid_coordinate(coordinate):
            return
        region = self._get_cell_region(coordinate)
        self._refresh_region(region)

    def refresh_row(self, row_index: int) -> None:
        """Refresh the row at the given index.

        Args:
            row_index: The index of the row to refresh.
        """
        if not self.is_valid_row_index(row_index):
            return

        region = self._get_row_region(row_index)
        self._refresh_region(region)

    def refresh_column(self, column_index: int) -> None:
        """Refresh the column at the given index.

        Args:
            column_index: The index of the column to refresh.
        """
        if not self.is_valid_column_index(column_index):
            return

        region = self._get_column_region(column_index)
        self._refresh_region(region)

    def _refresh_region(self, region: Region) -> None:
        """Refresh a region of the DataTable, if it's visible within
        the window. This method will translate the region to account
        for scrolling."""
        if not self.window_region.overlaps(region):
            return
        region = region.translate(-self.scroll_offset)
        self.refresh(region)

    def is_valid_row_index(self, row_index: int) -> bool:
        """Return a boolean indicating whether the row_index is within table bounds.

        Args:
            row_index: The row index to check.

        Returns:
            True if the row index is within the bounds of the table.
        """
        return 0 <= row_index < len(self.rows)

    def is_valid_column_index(self, column_index: int) -> bool:
        """Return a boolean indicating whether the column_index is within table bounds.

        Args:
            column_index: The column index to check.

        Returns:
            True if the column index is within the bounds of the table.
        """
        return 0 <= column_index < len(self.columns)

    def is_valid_coordinate(self, coordinate: Coordinate) -> bool:
        """Return a boolean indicating whether the given coordinate is valid.

        Args:
            coordinate: The coordinate to validate.

        Returns:
            True if the coordinate is within the bounds of the table.
        """
        row_index, column_index = coordinate
        return self.is_valid_row_index(row_index) and self.is_valid_column_index(
            column_index
        )

    @property
    def ordered_columns(self) -> list[Column]:
        """The list of Columns in the DataTable, ordered as they appear on screen."""
        column_indices = range(len(self.columns))
        column_keys = [
            self._column_locations.get_key(index) for index in column_indices
        ]
        ordered_columns = [self.columns[key] for key in column_keys]
        return ordered_columns

    @property
    def ordered_rows(self) -> list[Row]:
        """The list of Rows in the DataTable, ordered as they appear on screen."""
        num_rows = self.row_count
        update_count = self._update_count
        cache_key = (num_rows, update_count)
        if cache_key in self._ordered_row_cache:
            ordered_rows = self._ordered_row_cache[cache_key]
        else:
            row_indices = range(num_rows)
            ordered_rows = []
            for row_index in row_indices:
                row_key = self._row_locations.get_key(row_index)
                row = self.rows[row_key]
                ordered_rows.append(row)
            self._ordered_row_cache[cache_key] = ordered_rows
        return ordered_rows

    @property
    def _should_render_row_labels(self) -> bool:
        """Whether row labels should be rendered or not."""
        return self._labelled_row_exists and self.show_row_labels

    def _get_row_renderables(self, row_index: int) -> RenderedRow:
        """Get renderables for the row currently at the given row index.

        Args:
            row_index: Index of the row.

        Returns:
            A RenderedRow containing the optional label and the rendered cells.
        """
        ordered_columns = self.ordered_columns
        if row_index == -1:
            header_row: list[RenderableType] = [
                column.label for column in ordered_columns
            ]
            # This is the cell where header and row labels intersect
            return RenderedRow(None, header_row)

        ordered_row = self.get_row_at(row_index)
        empty = Text()

        formatted_row_cells = [
            Text() if datum is None else default_cell_formatter(datum) or empty
            for datum, _ in zip_longest(ordered_row, range(len(self.columns)))
        ]
        label = None
        if self._should_render_row_labels:
            row_metadata = self.rows.get(self._row_locations.get_key(row_index))
            label = (
                default_cell_formatter(row_metadata.label)
                if row_metadata.label
                else None
            )
        return RenderedRow(label, formatted_row_cells)

    def _render_cell(
        self,
        row_index: int,
        column_index: int,
        style: Style,
        width: int,
        cursor: bool = False,
        hover: bool = False,
    ) -> SegmentLines:
        """Render the given cell.

        Args:
            row_index: Index of the row.
            column_index: Index of the column.
            style: Style to apply.
            width: Width of the cell.
            cursor: Is this cell affected by cursor highlighting?
            hover: Is this cell affected by hover cursor highlighting?

        Returns:
            A list of segments per line.
        """
        is_header_cell = row_index == -1
        is_row_label_cell = column_index == -1

        is_fixed_style_cell = (
            not is_header_cell
            and not is_row_label_cell
            and (row_index < self.fixed_rows or column_index < self.fixed_columns)
        )

        get_component = self.get_component_styles
        show_cursor = self.show_cursor
        if hover and show_cursor and self._show_hover_cursor:
            style += get_component("datatable--hover").rich_style
            if is_header_cell:
                # Apply subtle variation in style for the fixed (blue background by
                # default) rows and columns affected by the cursor, to ensure we can
                # still differentiate between the labels and the data.
                style += get_component("datatable--header-hover").rich_style

        if cursor and show_cursor:
            style += get_component("datatable--cursor").rich_style
            if is_header_cell:
                style += get_component("datatable--header-cursor").rich_style
            elif is_fixed_style_cell:
                style += get_component("datatable--fixed-cursor").rich_style

        if is_header_cell:
            row_key = self._header_row_key
        else:
            row_key = self._row_locations.get_key(row_index)

        column_key = self._column_locations.get_key(column_index)
        cell_cache_key = (row_key, column_key, style, cursor, hover, self._update_count)

        if cell_cache_key not in self._cell_render_cache:
            style += Style.from_meta({"row": row_index, "column": column_index})
            height = self.header_height if is_header_cell else self.rows[row_key].height

            cell = self._get_row_renderables(row_index).cells[column_index]
            lines = self.app.console.render_lines(
                Padding(cell, (0, 1)),
                self.app.console.options.update_dimensions(width, height),
                style=style,
            )

            self._cell_render_cache[cell_cache_key] = lines

        return self._cell_render_cache[cell_cache_key]

    def _render_line_in_row(
        self,
        row_key: RowKey,
        line_no: int,
        base_style: Style,
        cursor_location: Coordinate,
        hover_location: Coordinate,
    ) -> tuple[SegmentLines, SegmentLines]:
        """Render a single line from a row in the DataTable.

        Args:
            row_key: The identifying key for this row.
            line_no: Line number (y-coordinate) within row. 0 is the first strip of
                cells in the row, line_no=1 is the next line in the row, and so on...
            base_style: Base style of row.
            cursor_location: The location of the cursor in the DataTable.
            hover_location: The location of the hover cursor in the DataTable.

        Returns:
            Lines for fixed cells, and Lines for scrollable cells.
        """
        cursor_type = self.cursor_type
        show_cursor = self.show_cursor

        cache_key = (
            row_key,
            line_no,
            base_style,
            cursor_location,
            hover_location,
            cursor_type,
            show_cursor,
            self._show_hover_cursor,
            self._update_count,
        )

        if cache_key in self._row_render_cache:
            return self._row_render_cache[cache_key]

        def _should_highlight(
            cursor: Coordinate,
            target_cell: Coordinate,
            type_of_cursor: CursorType,
        ) -> bool:
            """Determine whether we should highlight a cell given the location
            of the cursor, the location of the cell, and the type of cursor that
            is currently active."""
            if type_of_cursor == "cell":
                return cursor == target_cell
            elif type_of_cursor == "row":
                cursor_row, _ = cursor
                cell_row, _ = target_cell
                return cursor_row == cell_row
            elif type_of_cursor == "column":
                _, cursor_column = cursor
                _, cell_column = target_cell
                return cursor_column == cell_column
            else:
                return False

        is_header_row = row_key is self._header_row_key
        render_cell = self._render_cell

        if row_key in self._row_locations:
            row_index = self._row_locations.get(row_key)
        else:
            row_index = -1

        # If the row has a label, add it to fixed_row here with correct style.
        fixed_row = []
        header_style = self.get_component_styles("datatable--header").rich_style
        if self._labelled_row_exists and self.show_row_labels and not is_header_row:
            label_cell_lines = render_cell(
                row_index,
                -1,
                header_style,
                width=self._row_label_column_width,
                cursor=False,
                hover=False,
            )[line_no]
            fixed_row.append(label_cell_lines)

        if self.fixed_columns:
            fixed_style = self.get_component_styles("datatable--fixed").rich_style
            fixed_style += Style.from_meta({"fixed": True})
            for column_index, column in enumerate(
                self.ordered_columns[: self.fixed_columns]
            ):
                cell_location = Coordinate(row_index, column_index)
                fixed_cell_lines = render_cell(
                    row_index,
                    column_index,
                    header_style if is_header_row else fixed_style,
                    column.render_width,
                    cursor=_should_highlight(
                        cursor_location, cell_location, cursor_type
                    ),
                    hover=_should_highlight(hover_location, cell_location, cursor_type),
                )[line_no]
                fixed_row.append(fixed_cell_lines)

        is_header_row = row_key is self._header_row_key
        if is_header_row:
            row_style = self.get_component_styles("datatable--header").rich_style
        elif row_index < self.fixed_rows:
            row_style = self.get_component_styles("datatable--fixed").rich_style
        else:
            if self.zebra_stripes:
                component_row_style = (
                    "datatable--odd-row" if row_index % 2 else "datatable--even-row"
                )
                row_style = self.get_component_styles(component_row_style).rich_style
            else:
                row_style = base_style

        scrollable_row = []
        for column_index, column in enumerate(self.ordered_columns):
            cell_location = Coordinate(row_index, column_index)
            cell_lines = render_cell(
                row_index,
                column_index,
                row_style,
                column.render_width,
                cursor=_should_highlight(cursor_location, cell_location, cursor_type),
                hover=_should_highlight(hover_location, cell_location, cursor_type),
            )[line_no]
            scrollable_row.append(cell_lines)

        row_pair = (fixed_row, scrollable_row)
        self._row_render_cache[cache_key] = row_pair
        return row_pair

    def _get_offsets(self, y: int) -> tuple[RowKey, int]:
        """Get row key and line offset for a given line.

        Args:
            y: Y coordinate relative to DataTable top.

        Returns:
            Row key and line (y) offset within cell.
        """
        header_height = self.header_height
        y_offsets = self._y_offsets
        if self.show_header:
            if y < header_height:
                return self._header_row_key, y
            y -= header_height
        if y > len(y_offsets):
            raise LookupError("Y coord {y!r} is greater than total height")

        return y_offsets[y]

    def _render_line(self, y: int, x1: int, x2: int, base_style: Style) -> Strip:
        """Render a (possibly cropped) line in to a Strip (a list of segments
            representing a horizontal line).

        Args:
            y: Y coordinate of line
            x1: X start crop.
            x2: X end crop (exclusive).
            base_style: Style to apply to line.

        Returns:
            The Strip which represents this cropped line.
        """

        width = self.size.width

        try:
            row_key, y_offset_in_row = self._get_offsets(y)
        except LookupError:
            return Strip.blank(width, base_style)

        cache_key = (
            y,
            x1,
            x2,
            width,
            self.cursor_coordinate,
            self.hover_coordinate,
            base_style,
            self.cursor_type,
            self._show_hover_cursor,
            self._update_count,
        )
        if cache_key in self._line_cache:
            return self._line_cache[cache_key]

        fixed, scrollable = self._render_line_in_row(
            row_key,
            y_offset_in_row,
            base_style,
            cursor_location=self.cursor_coordinate,
            hover_location=self.hover_coordinate,
        )
        fixed_width = sum(
            column.render_width for column in self.ordered_columns[: self.fixed_columns]
        )

        fixed_line: list[Segment] = list(chain.from_iterable(fixed)) if fixed else []
        scrollable_line: list[Segment] = list(chain.from_iterable(scrollable))

        segments = fixed_line + line_crop(scrollable_line, x1 + fixed_width, x2, width)
        strip = Strip(segments).adjust_cell_length(width, base_style).simplify()

        self._line_cache[cache_key] = strip
        return strip

    def render_line(self, y: int) -> Strip:
        width, height = self.size
        scroll_x, scroll_y = self.scroll_offset

        fixed_row_keys: list[RowKey] = [
            self._row_locations.get_key(row_index)
            for row_index in range(self.fixed_rows)
        ]

        fixed_rows_height = sum(
            self.get_row_height(row_key) for row_key in fixed_row_keys
        )
        if self.show_header:
            fixed_rows_height += self.get_row_height(self._header_row_key)

        if y >= fixed_rows_height:
            y += scroll_y

        return self._render_line(y, scroll_x, scroll_x + width, self.rich_style)

    def on_mouse_move(self, event: events.MouseMove):
        """If the hover cursor is visible, display it by extracting the row
        and column metadata from the segments present in the cells."""
        self._set_hover_cursor(True)
        meta = event.style.meta
        if meta and self.show_cursor and self.cursor_type != "none":
            try:
                self.hover_coordinate = Coordinate(meta["row"], meta["column"])
            except KeyError:
                pass

    def _get_fixed_offset(self) -> Spacing:
        """Calculate the "fixed offset", that is the space to the top and left
        that is occupied by fixed rows and columns respectively. Fixed rows and columns
        are rows and columns that do not participate in scrolling."""
        top = self.header_height if self.show_header else 0
        top += sum(row.height for row in self.ordered_rows[: self.fixed_rows])
        left = sum(
            column.render_width for column in self.ordered_columns[: self.fixed_columns]
        )
        return Spacing(top, 0, 0, left)

    def sort(
        self,
        *columns: ColumnKey | str,
        reverse: bool = False,
    ) -> None:
        """Sort the rows in the DataTable by one or more column keys.

        Args:
            columns: One or more columns to sort by the values in.
            reverse: If True, the sort order will be reversed.
        """

        def sort_by_column_keys(
            row: tuple[RowKey, dict[ColumnKey | str, CellType]]
        ) -> Any:
            _, row_data = row
            result = itemgetter(*columns)(row_data)
            return result

        ordered_rows = sorted(
            self._data.items(), key=sort_by_column_keys, reverse=reverse
        )
        self._row_locations = TwoWayDict(
            {key: new_index for new_index, (key, _) in enumerate(ordered_rows)}
        )
        self._update_count += 1
        self.refresh()

    def _scroll_cursor_into_view(self, animate: bool = False) -> None:
        """When the cursor is at a boundary of the DataTable and moves out
        of view, this method handles scrolling to ensure it remains visible."""
        fixed_offset = self._get_fixed_offset()
        top, _, _, left = fixed_offset

        if self.cursor_type == "row":
            x, y, width, height = self._get_row_region(self.cursor_row)
            region = Region(int(self.scroll_x) + left, y, width - left, height)
        elif self.cursor_type == "column":
            x, y, width, height = self._get_column_region(self.cursor_column)
            region = Region(x, int(self.scroll_y) + top, width, height - top)
        else:
            region = self._get_cell_region(self.cursor_coordinate)

        self.scroll_to_region(region, animate=animate, spacing=fixed_offset)

    def _set_hover_cursor(self, active: bool) -> None:
        """Set whether the hover cursor (the faint cursor you see when you
        hover the mouse cursor over a cell) is visible or not. Typically,
        when you interact with the keyboard, you want to switch the hover
        cursor off.

        Args:
            active: Display the hover cursor.
        """
        self._show_hover_cursor = active
        cursor_type = self.cursor_type
        if cursor_type == "column":
            self.refresh_column(self.hover_column)
        elif cursor_type == "row":
            self.refresh_row(self.hover_row)
        elif cursor_type == "cell":
            self.refresh_coordinate(self.hover_coordinate)

    def on_click(self, event: events.Click) -> None:
        self._set_hover_cursor(True)
        meta = self.get_style_at(event.x, event.y).meta
        if not meta:
            return

        row_index = meta["row"]
        column_index = meta["column"]
        is_header_click = self.show_header and row_index == -1
        if is_header_click:
            # Header clicks work even if cursor is off, and doesn't move the cursor.
            column = self.ordered_columns[column_index]
            message = DataTable.HeaderSelected(
                self, column.key, column_index, label=column.label
            )
            self.post_message_no_wait(message)
        elif self.show_cursor and self.cursor_type != "none":
            # Only post selection events if there is a visible row/col/cell cursor.
            self.cursor_coordinate = Coordinate(row_index, column_index)
            self._post_selected_message()
            self._scroll_cursor_into_view(animate=True)
            event.stop()

    def action_cursor_up(self) -> None:
        self._set_hover_cursor(False)
        cursor_type = self.cursor_type
        if self.show_cursor and (cursor_type == "cell" or cursor_type == "row"):
            self.cursor_coordinate = self.cursor_coordinate.up()
            self._scroll_cursor_into_view()
        else:
            # If the cursor doesn't move up (e.g. column cursor can't go up),
            # then ensure that we instead scroll the DataTable.
            super().action_scroll_up()

    def action_cursor_down(self) -> None:
        self._set_hover_cursor(False)
        cursor_type = self.cursor_type
        if self.show_cursor and (cursor_type == "cell" or cursor_type == "row"):
            self.cursor_coordinate = self.cursor_coordinate.down()
            self._scroll_cursor_into_view()
        else:
            super().action_scroll_down()

    def action_cursor_right(self) -> None:
        self._set_hover_cursor(False)
        cursor_type = self.cursor_type
        if self.show_cursor and (cursor_type == "cell" or cursor_type == "column"):
            self.cursor_coordinate = self.cursor_coordinate.right()
            self._scroll_cursor_into_view(animate=True)
        else:
            super().action_scroll_right()

    def action_cursor_left(self) -> None:
        self._set_hover_cursor(False)
        cursor_type = self.cursor_type
        if self.show_cursor and (cursor_type == "cell" or cursor_type == "column"):
            self.cursor_coordinate = self.cursor_coordinate.left()
            self._scroll_cursor_into_view(animate=True)
        else:
            super().action_scroll_left()

    def action_select_cursor(self) -> None:
        self._set_hover_cursor(False)
        if self.show_cursor and self.cursor_type != "none":
            self._post_selected_message()

    def _post_selected_message(self):
        """Post the appropriate message for a selection based on the `cursor_type`."""
        cursor_coordinate = self.cursor_coordinate
        cursor_type = self.cursor_type
        cell_key = self.coordinate_to_cell_key(cursor_coordinate)
        if cursor_type == "cell":
            self.post_message_no_wait(
                DataTable.CellSelected(
                    self,
                    self.get_cell_at(cursor_coordinate),
                    coordinate=cursor_coordinate,
                    cell_key=cell_key,
                )
            )
        elif cursor_type == "row":
            row_index, _ = cursor_coordinate
            row_key, _ = cell_key
            self.post_message_no_wait(DataTable.RowSelected(self, row_index, row_key))
        elif cursor_type == "column":
            _, column_index = cursor_coordinate
            _, column_key = cell_key
            self.post_message_no_wait(
                DataTable.ColumnSelected(self, column_index, column_key)
            )
