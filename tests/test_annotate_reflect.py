"""Reflection pass for the annotate activities.

The reflect pass is a second, separately-configured LLM call that critiques and
revises the first-pass annotation. It runs only when a ``reflect_model`` was
supplied (the env-level gate) AND the per-run ``reflect`` flag is set.
"""

import asyncio

from doci.activities.annotate_image import AnnotateImage, ImageAnnotation
from doci.activities.annotate_text import AnnotateText, TextAnnotation, TextFact


class _FakeStructured:
    def __init__(self, result, calls):
        self._result = result
        self._calls = calls

    async def ainvoke(self, messages):
        self._calls.append(messages)
        return self._result


class _FakeModel:
    """A stand-in chat model whose ``with_structured_output`` returns a fake that
    records its calls and returns a fixed result."""

    def __init__(self, result):
        self._result = result
        self.calls: list = []

    def with_structured_output(self, _schema):
        return _FakeStructured(self._result, self.calls)


def _text(category: str) -> TextAnnotation:
    return TextAnnotation(
        category=category,
        description="d",
        facts=[TextFact(subject="s", value="v", source="q")],
    )


def test_reflect_unavailable_when_no_reflect_model():
    """env gate: no reflect_model ⇒ reflection never runs, even with reflect=True."""
    first = _FakeModel(_text("first"))
    act = AnnotateText(first)
    out = asyncio.run(act("some text", reflect=True))
    assert out.category == "first"
    assert len(first.calls) == 1  # only the first pass


def test_reflect_skipped_when_per_run_flag_off():
    """per-run gate: reflect_model present but reflect=False ⇒ not called."""
    first = _FakeModel(_text("first"))
    reflect = _FakeModel(_text("reflected"))
    act = AnnotateText(first, reflect_model=reflect)
    out = asyncio.run(act("some text", reflect=False))
    assert out.category == "first"
    assert len(reflect.calls) == 0


def test_reflect_runs_and_sees_first_pass():
    """both gates on ⇒ reflect runs, returns its result, sees the first-pass output."""
    first = _FakeModel(_text("first"))
    reflect = _FakeModel(_text("reflected"))
    act = AnnotateText(first, reflect_model=reflect)
    out = asyncio.run(act("some text", reflect=True))
    assert out.category == "reflected"
    assert len(reflect.calls) == 1
    # the reflect prompt must carry the first-pass annotation for critique
    blob = str(reflect.calls[0])
    assert "first" in blob


def test_reflect_max_iters_caps_passes():
    """LLM_REFLECT_MAX_ITERS bounds the number of critique rounds."""
    first = _FakeModel(_text("first"))
    reflect = _FakeModel(_text("reflected"))
    act = AnnotateText(first, reflect_model=reflect, reflect_max_iters=3)
    asyncio.run(act("some text", reflect=True))
    assert len(reflect.calls) == 3


def test_image_reflect_runs():
    """image activity reflects the same way (both gates on)."""
    img = ImageAnnotation(category="first", description="d")
    reflected = ImageAnnotation(category="reflected", description="d")
    first = _FakeModel(img)
    reflect = _FakeModel(reflected)
    act = AnnotateImage(first, reflect_model=reflect)
    out = asyncio.run(act(b"image-bytes", reflect=True))
    assert out.category == "reflected"
    assert len(reflect.calls) == 1
