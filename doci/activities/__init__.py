"""Activities — pure units of work, free of orchestration concerns."""

from doci.activities.annotate_image import (
    AnnotateImage,
    ImageAnnotation,
    VisualElement,
)
from doci.activities.annotate_text import (
    AnnotateText,
    TextAnnotation,
    TextFact,
)
from doci.activities.create_thumb_image import CreateThumbImage
from doci.activities.create_thumb_pdf import CreateThumbPdf
from doci.activities.download_media import DownloadMedia
from doci.activities.ensure_thumb import EnsureThumb
from doci.activities.extract_content_image import ExtractContentImage
from doci.activities.extract_content_pdf import ExtractContentPdf
from doci.activities.finalize_document import FinalizeDocument
from doci.activities.render_image_pdf import RenderImagePdf
from doci.activities.save_result_to_disk import SaveResult, SaveResultToDisk
from doci.activities.save_result_to_postgres import SaveResultToPostgres
from doci.activities.split_pdf import PdfPage, SplitPdf

__all__ = [
    "FinalizeDocument",
    "ExtractContentPdf",
    "ExtractContentImage",
    "AnnotateImage",
    "ImageAnnotation",
    "VisualElement",
    "AnnotateText",
    "TextAnnotation",
    "TextFact",
    "CreateThumbPdf",
    "CreateThumbImage",
    "DownloadMedia",
    "EnsureThumb",
    "SplitPdf",
    "PdfPage",
    "RenderImagePdf",
    "SaveResultToDisk",
    "SaveResultToPostgres",
    "SaveResult",
]
