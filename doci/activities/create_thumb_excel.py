"""Activity: render an .xlsx as a small, content-obfuscated PNG thumbnail.

A cell-occupancy "minimap": each cell of the first sheet becomes a small gray
block shaded by type — header / text / number — with empty cells left white. The
table's shape, size, and density are visible; the actual values are not. Returns
raw PNG bytes (store as a ``MediaType.THUMB`` derivative). Mirrors CreateThumbPdf;
PyMuPDF + openpyxl, no new deps.
"""

import io

import openpyxl
import pymupdf
from opentelemetry.trace import SpanKind

from doci.telemetry import traced, with_metrics, with_span

# Grayscale shades per cell type (0=black .. 1=white); empty cells stay white.
_SHADES = {"header": 0.35, "text": 0.62, "number": 0.80}


def _kind(value: object, *, is_header: bool) -> str | None:
    if value is None or value == "":
        return None
    if is_header:
        return "header"
    if isinstance(value, bool):  # bool is an int subclass — treat as text
        return "text"
    if isinstance(value, (int, float)):
        return "number"
    return "text"


@traced
class CreateThumbExcel:
    """Render a workbook's first sheet as a small, obfuscated cell-grid PNG."""

    def __init__(
        self,
        *,
        max_rows: int = 64,
        max_cols: int = 48,
        cell_px: int = 4,
    ) -> None:
        self._max_rows = max(1, max_rows)
        self._max_cols = max(1, max_cols)
        self._cell = max(1, cell_px)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def __call__(self, data: bytes) -> bytes:
        """Return a small, content-obfuscated PNG of the first sheet as bytes."""
        return self._render(data)

    def _render(self, data: bytes) -> bytes:
        grid = self._grid(data)
        n_rows = len(grid)
        n_cols = max((len(r) for r in grid), default=0)
        cw = self._cell
        width = max(1, n_cols * cw)
        height = max(1, n_rows * cw)
        out = pymupdf.open()
        try:
            page = out.new_page(width=width, height=height)
            for r, row in enumerate(grid):
                for c, kind in enumerate(row):
                    if kind is None:
                        continue
                    s = _SHADES[kind]
                    page.draw_rect(
                        pymupdf.Rect(c * cw, r * cw, (c + 1) * cw, (r + 1) * cw),
                        fill=(s, s, s),
                        color=None,
                        width=0,
                    )
            return page.get_pixmap(colorspace=pymupdf.csGRAY).tobytes("png")
        finally:
            out.close()

    def _grid(self, data: bytes) -> list[list[str | None]]:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            ws = wb.worksheets[0]
            grid: list[list[str | None]] = []
            for r, row in enumerate(ws.iter_rows(values_only=True)):
                if r >= self._max_rows:
                    break
                grid.append([_kind(v, is_header=r == 0) for v in row[: self._max_cols]])
            return grid
        finally:
            wb.close()
