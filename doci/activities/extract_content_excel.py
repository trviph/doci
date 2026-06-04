"""Activity: extract an .xlsx media into paginated Markdown tables.

Downloads the stored workbook, then yields it sheet by sheet as GitHub-flavored
Markdown tables, paginated to at most ``max_rows_per_page`` data rows per page.
Each page repeats its sheet's header row so it stands alone.
"""

import io
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from doci.media import MediaService


@dataclass(frozen=True, slots=True)
class ExcelPage:
    """One paginated slice of a sheet, rendered as a Markdown table."""

    sheet_name: str
    row_from: (
        int  # 1-based, inclusive; data-row index within the sheet (header excluded)
    )
    row_to: int  # 1-based, inclusive
    content: str  # GFM table: header row + this page's data rows


def _cell(value: Any) -> str:
    """Render a cell value as Markdown-table-safe text."""
    if value is None:
        return ""
    # Collapse newlines/CR so a value can't break the row, and escape pipes.
    text = str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def _row_md(cells: list[str], width: int) -> str:
    """Render one Markdown table row, padded/truncated to ``width`` columns."""
    padded = (cells + [""] * width)[:width]
    return "| " + " | ".join(padded) + " |"


class ExtractContentExcel:
    """Download an .xlsx media and yield it as paginated Markdown tables."""

    def __init__(self, media: MediaService, *, max_rows_per_page: int = 100) -> None:
        self._media = media
        self._max_rows = max(1, max_rows_per_page)

    async def __call__(self, media_id: UUID) -> AsyncIterator[ExcelPage]:
        # openpyxl needs the full, seekable file (an .xlsx is a zip whose central
        # directory sits at the end), so download the whole object before parsing.
        data = await self._media.download(media_id)
        for page in self._iter_pages(data):
            yield page

    def _iter_pages(self, data: bytes) -> Iterator[ExcelPage]:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                yield from self._sheet_pages(ws)
        finally:
            wb.close()

    def _sheet_pages(self, ws: Worksheet) -> Iterator[ExcelPage]:
        rows = ws.iter_rows(values_only=True)
        try:
            header = [_cell(v) for v in next(rows)]
        except StopIteration:
            return  # empty sheet — nothing to paginate
        width = len(header)
        if width == 0:
            return
        separator = "| " + " | ".join(["---"] * width) + " |"
        head = f"{_row_md(header, width)}\n{separator}"

        batch: list[str] = []
        start = 1  # 1-based data-row index (header excluded)
        index = 0
        for values in rows:
            index += 1
            batch.append(_row_md([_cell(v) for v in values], width))
            if len(batch) >= self._max_rows:
                yield self._page(ws.title, start, index, head, batch)
                batch = []
                start = index + 1
        if batch:
            yield self._page(ws.title, start, index, head, batch)

    @staticmethod
    def _page(
        sheet_name: str, row_from: int, row_to: int, head: str, rows: list[str]
    ) -> ExcelPage:
        return ExcelPage(
            sheet_name=sheet_name,
            row_from=row_from,
            row_to=row_to,
            content="\n".join([head, *rows]),
        )
