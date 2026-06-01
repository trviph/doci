"""MIME-type detection for accepted uploads.

Binary formats are identified by magic bytes (ported/extended from argos
`mime.go`). Modern Office files (docx/xlsx/pptx) are ZIP containers, classified
by peeking inside the archive. Raw text (txt/markdown/csv) has no magic, so it's
accepted only when the bytes decode as UTF-8 and contain no dangerous control
characters; the subtype is chosen from the uploaded filename extension.

Detection runs on the full (size-bounded) upload buffer plus the filename.
"""

import io
import re
import zipfile
from collections.abc import Callable
from pathlib import PurePosixPath

#: Bytes needed to identify binary formats; 12 covers RIFF+WEBP (bytes 0-3, 8-11).
HEADER_LEN = 12

# Images / documents (binary, magic-byte detectable).
MIME_PDF = "application/pdf"
MIME_PNG = "image/png"
MIME_JPEG = "image/jpeg"
MIME_GIF = "image/gif"
MIME_WEBP = "image/webp"
MIME_BMP = "image/bmp"
MIME_TIFF = "image/tiff"
# Modern Office Open XML (ZIP containers).
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
# Text.
MIME_TXT = "text/plain"
MIME_MARKDOWN = "text/markdown"
MIME_CSV = "text/csv"


def _prefix(magic: bytes) -> Callable[[bytes], bool]:
    return lambda h: h.startswith(magic)


def _match_webp(h: bytes) -> bool:
    return len(h) >= 12 and h[0:4] == b"RIFF" and h[8:12] == b"WEBP"


# Binary magic, most-specific first.
_MAGIC: list[tuple[str, Callable[[bytes], bool]]] = [
    (MIME_PDF, _prefix(b"%PDF")),
    (MIME_PNG, _prefix(b"\x89PNG\r\n\x1a\n")),
    (MIME_JPEG, _prefix(b"\xff\xd8\xff")),
    (MIME_GIF, _prefix(b"GIF87a")),
    (MIME_GIF, _prefix(b"GIF89a")),
    (MIME_WEBP, _match_webp),
    (MIME_BMP, _prefix(b"BM")),
    (MIME_TIFF, _prefix(b"II*\x00")),  # little-endian
    (MIME_TIFF, _prefix(b"MM\x00*")),  # big-endian
]

# ZIP local-file-header signature (OOXML containers start with this).
_ZIP_MAGIC = b"PK\x03\x04"

#: Opens the NETSCAPE2.0 application extension found in animated GIFs.
NETSCAPE_MARKER = b"\x21\xff\x0bNETSCAPE2.0"

# Disallowed control bytes for "text": everything < 0x20 except TAB/LF/CR, plus DEL.
_BAD_CTRL = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_TEXT_BY_EXT = {
    ".md": MIME_MARKDOWN,
    ".markdown": MIME_MARKDOWN,
    ".csv": MIME_CSV,
    ".txt": MIME_TXT,
}


def is_gif87a(header: bytes) -> bool:
    """GIF87a cannot, by spec, contain animation."""
    return header.startswith(b"GIF87a")


def _classify_ooxml(data: bytes) -> str | None:
    """Classify a ZIP container as docx/xlsx/pptx (else None)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return None
    if any(n.startswith("word/") for n in names):
        return MIME_DOCX
    if any(n.startswith("xl/") for n in names):
        return MIME_XLSX
    if any(n.startswith("ppt/") for n in names):
        return MIME_PPTX
    return None


def _classify_text(data: bytes, filename: str | None) -> str | None:
    """Accept as text only if UTF-8 and free of dangerous control chars."""
    if _BAD_CTRL.search(data):
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    ext = PurePosixPath(filename or "").suffix.lower()
    return _TEXT_BY_EXT.get(ext, MIME_TXT)


def detect_mime(data: bytes, *, filename: str | None = None) -> str | None:
    """Detect the MIME type of an upload, or None if it's not an accepted type.

    Order: binary magic → OOXML zip → UTF-8 text. Legacy OLE2 office files and
    arbitrary binary/zip are rejected (None).
    """
    header = data[:HEADER_LEN]
    for mime, match in _MAGIC:
        if match(header):
            return mime
    if header.startswith(_ZIP_MAGIC):
        return _classify_ooxml(data)
    return _classify_text(data, filename)
