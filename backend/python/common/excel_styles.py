"""
Excel Styling Utility for Reliability Tools Suite

Provides consistent, modern, professional Excel formatting across all tools.
Uses openpyxl for styling with a clean API.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Any, Optional, Union
import re
import pandas as pd

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# XML 1.0 illegal characters pattern
# These characters cause Excel "file is corrupted" errors when present in cell data
# Allowed: #x9 (tab), #xA (newline), #xD (carriage return), #x20-#xD7FF, #xE000-#xFFFD
_ILLEGAL_XML_CHARS_RE = re.compile(
    r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F\uD800-\uDFFF\uFFFE\uFFFF]'
)


def sanitize_for_excel(value: Any) -> Any:
    """Sanitize a value for safe Excel/XML storage.

    Removes illegal XML 1.0 characters that cause Excel to report
    "file is corrupted" warnings. These characters are typically
    invisible control characters that may exist in source data.

    Args:
        value: Any cell value (string, number, etc.)

    Returns:
        Sanitized value safe for Excel
    """
    if isinstance(value, str):
        # Remove illegal XML characters
        return _ILLEGAL_XML_CHARS_RE.sub('', value)
    return value


@dataclass
class ExcelColors:
    """Centralized color definitions for Excel styling."""

    # Primary colors
    HEADER_BG: str = "2E5A88"      # Steel blue - professional but modern
    HEADER_FG: str = "FFFFFF"      # White
    DATA_TEXT: str = "333333"      # Dark gray for readability
    BORDER: str = "B4B4B4"         # Medium gray, subtle
    ROW_ALT: str = "F5F5F5"        # Very light gray for zebra striping

    # Semantic colors - Fill
    ERROR_FILL: str = "FFC7CE"     # Light red
    WARNING_FILL: str = "FFEB9C"   # Light orange/yellow
    INFO_FILL: str = "FFFFC7"      # Light yellow
    SUCCESS_FILL: str = "C6EFCE"   # Light green
    HIGHLIGHT_FILL: str = "BDD7EE" # Light blue
    NEUTRAL_FILL: str = "D9D9D9"   # Light gray
    GAP_FILL: str = "FFFF00"       # Bright yellow - missing sequence gap
    UNVERIFIED_FILL: str = "E8E8E8"  # Light gray - distinct from GAP yellow

    # Semantic colors - Font
    ERROR_FONT: str = "9C0006"     # Dark red
    WARNING_FONT: str = "9C5700"   # Dark orange
    INFO_FONT: str = "9C6500"      # Dark yellow/brown
    SUCCESS_FONT: str = "006100"   # Dark green
    HIGHLIGHT_FONT: str = "1F4E79" # Dark blue
    NEUTRAL_FONT: str = "000000"   # Black
    GAP_FONT: str = "000000"       # Black on bright yellow
    UNVERIFIED_FONT: str = "666666"  # Dark gray text for unverified rows


class StylePresets:
    """Pre-configured openpyxl style objects for consistent formatting."""

    FONT_NAME = "Aptos"
    FONT_SIZE = 11

    def __init__(self, colors: ExcelColors = None):
        self.colors = colors or ExcelColors()
        self._build_styles()

    def _build_styles(self):
        """Build all style objects from color definitions."""
        c = self.colors

        # Header styles
        self.header_font = Font(
            name=self.FONT_NAME, size=self.FONT_SIZE,
            bold=True, color=c.HEADER_FG
        )
        self.header_fill = PatternFill(
            start_color=c.HEADER_BG, end_color=c.HEADER_BG, fill_type="solid"
        )
        self.header_alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )

        # Data styles
        self.data_font = Font(
            name=self.FONT_NAME, size=self.FONT_SIZE, color=c.DATA_TEXT
        )
        self.data_alignment = Alignment(
            horizontal="left", vertical="top", wrap_text=True
        )

        # Border
        self.thin_border = Border(
            left=Side(style="thin", color=c.BORDER),
            right=Side(style="thin", color=c.BORDER),
            top=Side(style="thin", color=c.BORDER),
            bottom=Side(style="thin", color=c.BORDER)
        )

        # Alternate row fill
        self.alt_row_fill = PatternFill(
            start_color=c.ROW_ALT, end_color=c.ROW_ALT, fill_type="solid"
        )

        # Semantic fills and fonts
        self._semantic_styles = {
            "error": (
                PatternFill(start_color=c.ERROR_FILL, end_color=c.ERROR_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.ERROR_FONT)
            ),
            "warning": (
                PatternFill(start_color=c.WARNING_FILL, end_color=c.WARNING_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.WARNING_FONT)
            ),
            "info": (
                PatternFill(start_color=c.INFO_FILL, end_color=c.INFO_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.INFO_FONT)
            ),
            "success": (
                PatternFill(start_color=c.SUCCESS_FILL, end_color=c.SUCCESS_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.SUCCESS_FONT)
            ),
            "highlight": (
                PatternFill(start_color=c.HIGHLIGHT_FILL, end_color=c.HIGHLIGHT_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.HIGHLIGHT_FONT)
            ),
            "neutral": (
                PatternFill(start_color=c.NEUTRAL_FILL, end_color=c.NEUTRAL_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.NEUTRAL_FONT)
            ),
            "gap": (
                PatternFill(start_color=c.GAP_FILL, end_color=c.GAP_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.GAP_FONT)
            ),
            "unverified": (
                PatternFill(start_color=c.UNVERIFIED_FILL, end_color=c.UNVERIFIED_FILL, fill_type="solid"),
                Font(name=self.FONT_NAME, size=self.FONT_SIZE, color=c.UNVERIFIED_FONT)
            ),
        }

    def get_row_style(self, style_name: str):
        """
        Get (fill, font) tuple for a semantic style name.

        Args:
            style_name: One of 'error', 'warning', 'info', 'success',
                       'highlight', 'neutral', or 'default'

        Returns:
            Tuple of (PatternFill, Font) or (None, data_font) for default
        """
        if style_name in self._semantic_styles:
            return self._semantic_styles[style_name]
        return (None, self.data_font)


# Global preset instance for convenience
COLORS = ExcelColors()
PRESETS = StylePresets()

# Standard number formats for consistent Excel output
NUMBER_FORMATS = {
    "scientific": "0.00E+00",      # For failure rates (e.g., 1.23E-06)
    "decimal_6": "0.000000",       # Alternative for failure rates
    "decimal_4": "0.0000",         # For ratios
    "percentage": "0.00%",         # For percentages
    "integer": "#,##0",            # For counts with thousand separator
    "fraction": "# ???/???",       # For part usage fractions
}


def calculate_column_widths(
    df: pd.DataFrame,
    min_width: int = 8,
    max_width: int = 50,
    padding: int = 2,
    sample_rows: int = 100
) -> Dict[str, float]:
    """
    Calculate optimal column widths based on content.

    Args:
        df: DataFrame to analyze
        min_width: Minimum column width
        max_width: Maximum column width (prevents overly wide columns)
        padding: Extra characters to add for visual breathing room
        sample_rows: Number of rows to sample for large datasets

    Returns:
        Dict mapping column names to calculated widths
    """
    widths = {}

    # Sample for large datasets
    sample_df = df.head(sample_rows) if len(df) > sample_rows else df

    for col in df.columns:
        # Start with header length
        max_len = len(str(col))

        # Check data values
        for val in sample_df[col]:
            if pd.isna(val):
                continue
            # Handle multi-line cells - take longest line
            val_str = str(val)
            lines = val_str.split('\n')
            line_len = max(len(line) for line in lines)
            max_len = max(max_len, line_len)

        # Apply constraints
        width = min(max(max_len + padding, min_width), max_width)
        widths[col] = width

    return widths


def style_worksheet(
    ws: Worksheet,
    df: pd.DataFrame,
    presets: StylePresets = None,
    row_style_func: Callable[[pd.Series, int], str] = None,
    freeze_header: bool = True,
    freeze_first_col: bool = False,
    auto_filter: bool = True,
    auto_width: bool = True,
    min_width: int = 8,
    max_width: int = 50,
    alternate_rows: bool = False,
    cancel_check: Callable[[], bool] = None
) -> None:
    """
    Apply comprehensive styling to a worksheet.

    Args:
        ws: openpyxl Worksheet to style
        df: DataFrame that was written to the worksheet
        presets: StylePresets instance (uses global PRESETS if None)
        row_style_func: Optional function(row_series, row_index) -> style_name
                       Returns 'error', 'warning', 'info', 'success',
                       'highlight', 'neutral', or 'default'
        freeze_header: Freeze the header row for scrolling
        freeze_first_col: Freeze the first column for horizontal scrolling
        auto_filter: Add auto-filter dropdowns to headers
        auto_width: Auto-size columns based on content
        min_width: Minimum column width (if auto_width)
        max_width: Maximum column width (if auto_width)
        alternate_rows: Apply zebra striping to rows
        cancel_check: Optional callable returning True if cancelled
    """
    if presets is None:
        presets = PRESETS

    if df.empty:
        return

    num_cols = len(df.columns)
    num_rows = len(df) + 1  # +1 for header

    # Style header row (row 1)
    for col_idx in range(1, num_cols + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = presets.header_font
        cell.fill = presets.header_fill
        cell.alignment = presets.header_alignment
        cell.border = presets.thin_border

    # Style data rows (row 2 onwards)
    for row_idx in range(2, num_rows + 1):
        # Cancel check every 100 rows for minimal overhead
        if cancel_check and row_idx % 100 == 0 and cancel_check():
            from .cancellation import CancellationError
            raise CancellationError("Worksheet styling cancelled.")

        df_row_idx = row_idx - 2  # DataFrame index (0-based)

        # Determine row style
        fill = None
        font = presets.data_font

        if row_style_func is not None and df_row_idx < len(df):
            try:
                style_name = row_style_func(df.iloc[df_row_idx], df_row_idx)
                fill, font = presets.get_row_style(style_name)
            except Exception:
                pass  # Fall back to default styling

        # Apply alternate row coloring if no semantic style and enabled
        if fill is None and alternate_rows and (row_idx % 2 == 0):
            fill = presets.alt_row_fill

        # Apply styles to each cell in the row
        for col_idx in range(1, num_cols + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = font
            cell.alignment = presets.data_alignment
            cell.border = presets.thin_border
            # Only apply fill to cells that have data (not empty)
            if fill is not None and cell.value not in (None, "", " "):
                cell.fill = fill

    # Auto-size columns
    if auto_width:
        widths = calculate_column_widths(df, min_width, max_width)
        for col_idx, col_name in enumerate(df.columns, start=1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = widths.get(col_name, 12)

    # Freeze panes (header row and/or first column)
    if freeze_header and freeze_first_col:
        ws.freeze_panes = "B2"  # Freeze both header and first column
    elif freeze_header:
        ws.freeze_panes = "A2"  # Freeze header only
    elif freeze_first_col:
        ws.freeze_panes = "B1"  # Freeze first column only

    # Add auto-filter
    if auto_filter and num_cols > 0:
        last_col = get_column_letter(num_cols)
        ws.auto_filter.ref = f"A1:{last_col}{num_rows}"


def write_styled_excel(
    df: pd.DataFrame,
    output_path: str,
    sheet_name: str = "Sheet1",
    row_style_func: Callable[[pd.Series, int], str] = None,
    freeze_header: bool = True,
    freeze_first_col: bool = False,
    auto_filter: bool = True,
    auto_width: bool = True,
    min_width: int = 8,
    max_width: int = 50,
    alternate_rows: bool = False
) -> str:
    """
    Convenience function to write a styled Excel file with a single sheet.

    Args:
        df: DataFrame to write
        output_path: Path for the output Excel file
        sheet_name: Name for the worksheet
        row_style_func: Optional function(row_series, row_index) -> style_name
        freeze_header: Freeze the header row
        freeze_first_col: Freeze the first column for horizontal scrolling
        auto_filter: Add auto-filter to headers
        auto_width: Auto-size columns
        min_width: Minimum column width
        max_width: Maximum column width
        alternate_rows: Apply zebra striping

    Returns:
        The output path (for chaining)
    """
    # Create workbook and write data
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    # Write DataFrame to worksheet
    # Header row
    for col_idx, col_name in enumerate(df.columns, start=1):
        ws.cell(row=1, column=col_idx, value=sanitize_for_excel(str(col_name)))

    # Data rows
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        for col_idx, value in enumerate(row, start=1):
            # Convert NaN to empty string
            if pd.isna(value):
                value = ""
            else:
                value = sanitize_for_excel(value)
            ws.cell(row=row_idx, column=col_idx, value=value)

    # Apply styling
    style_worksheet(
        ws, df,
        row_style_func=row_style_func,
        freeze_header=freeze_header,
        freeze_first_col=freeze_first_col,
        auto_filter=auto_filter,
        auto_width=auto_width,
        min_width=min_width,
        max_width=max_width,
        alternate_rows=alternate_rows
    )

    # Save
    wb.save(output_path)
    return output_path


def write_df_to_sheet(ws: Worksheet, df: pd.DataFrame) -> None:
    """
    Write a DataFrame to a worksheet (data only, no styling).

    All string values are sanitized to remove illegal XML characters
    that would cause Excel to report "file is corrupted" errors.

    Args:
        ws: Worksheet to write to
        df: DataFrame to write
    """
    # Header row (sanitize column names)
    for col_idx, col_name in enumerate(df.columns, start=1):
        ws.cell(row=1, column=col_idx, value=sanitize_for_excel(str(col_name)))

    # Data rows (sanitize all values)
    for row_idx, (_, row) in enumerate(df.iterrows(), start=2):
        for col_idx, value in enumerate(row, start=1):
            if pd.isna(value):
                value = ""
            else:
                value = sanitize_for_excel(value)
            ws.cell(row=row_idx, column=col_idx, value=value)
