"""Shared helpers for vision-LLM activities (image-input)."""

import base64

from langchain_core.messages import HumanMessage

from doci.media.mime import detect_mime


def image_message(prompt: str, image: bytes) -> HumanMessage:
    """A multimodal user message: instruction ``prompt`` + a base64 image block."""
    return HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {
                "type": "image",
                "source_type": "base64",
                "mime_type": detect_mime(image) or "image/png",
                "data": base64.standard_b64encode(image).decode("ascii"),
            },
        ]
    )
