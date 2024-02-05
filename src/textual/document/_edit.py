from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from textual.document._document import EditResult, Location, Selection

if TYPE_CHECKING:
    from textual.widgets import TextArea


@dataclass
class Edit:
    """Implements the Undoable protocol to replace text at some range within a document."""

    text: str
    """The text to insert. An empty string is equivalent to deletion."""
    from_location: Location
    """The start location of the insert."""
    to_location: Location
    """The end location of the insert"""
    maintain_selection_offset: bool
    """If True, the selection will maintain its offset to the replacement range."""
    _updated_selection: Selection | None = field(init=False, default=None)
    """Where the selection should move to after the replace happens."""
    _edit_result: EditResult | None = field(init=False, default=None)
    """The result of doing the edit."""

    def do(self, text_area: TextArea) -> EditResult:
        """Perform the edit operation.

        Args:
            text_area: The `TextArea` to perform the edit on.

        Returns:
            An `EditResult` containing information about the replace operation.
        """
        text = self.text

        edit_from = self.from_location
        edit_to = self.to_location

        # This code is mostly handling how we adjust TextArea.selection
        # when an edit is made to the document programmatically.
        # We want a user who is typing away to maintain their relative
        # position in the document even if an insert happens before
        # their cursor position.

        edit_top, edit_bottom = sorted((edit_from, edit_to))
        edit_bottom_row, edit_bottom_column = edit_bottom

        selection_start, selection_end = text_area.selection
        selection_start_row, selection_start_column = selection_start
        selection_end_row, selection_end_column = selection_end

        edit_result = text_area.document.replace_range(edit_from, edit_to, text)

        new_edit_to_row, new_edit_to_column = edit_result.end_location

        column_offset = new_edit_to_column - edit_bottom_column
        target_selection_start_column = (
            selection_start_column + column_offset
            if edit_bottom_row == selection_start_row
            and edit_bottom_column <= selection_start_column
            else selection_start_column
        )
        target_selection_end_column = (
            selection_end_column + column_offset
            if edit_bottom_row == selection_end_row
            and edit_bottom_column <= selection_end_column
            else selection_end_column
        )

        row_offset = new_edit_to_row - edit_bottom_row
        target_selection_start_row = selection_start_row + row_offset
        target_selection_end_row = selection_end_row + row_offset

        if self.maintain_selection_offset:
            self._updated_selection = Selection(
                start=(target_selection_start_row, target_selection_start_column),
                end=(target_selection_end_row, target_selection_end_column),
            )
        else:
            self._updated_selection = Selection.cursor(edit_result.end_location)

        self._edit_result = edit_result
        return edit_result

    def undo(self, text_area: TextArea) -> EditResult:
        """Undo the edit operation.

        Looks at the data stored in the edit, and performs the inverse operation of `Edit.do`.

        Args:
            text_area: The `TextArea` to undo the insert operation on.

        Returns:
            An `EditResult` containing information about the replace operation.
        """
        # This is where the selection will be updated to after the content is restored.
        target_from = self.from_location
        target_to = self.to_location

        target_top, target_bottom = sorted((target_to, target_from))

        # The text that was there before and is no longer there - needs to be inserted again.
        replaced_text = self._edit_result.replaced_text

        # The bounds of the new content
        # target_from -> edit_result.new_end
        edit_end = self._edit_result.end_location

        # Replace the span of the edit with the text that was originally there.
        undo_edit_result = text_area.document.replace_range(
            target_top, edit_end, replaced_text
        )

        # TODO - this should be a separate field
        self._updated_selection = Selection(target_from, target_to)

        return undo_edit_result

    def after(self, text_area: TextArea) -> None:
        """Possibly update the cursor location after the widget has been refreshed.

        Args:
            text_area: The `TextArea` this operation was performed on.
        """
        if self._updated_selection is not None:
            text_area.selection = self._updated_selection
        text_area.record_cursor_width()
