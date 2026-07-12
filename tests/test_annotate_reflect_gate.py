"""Env-level gate + per-run flag persistence for the annotation reflect pass."""

import pytest

from doci.activities.reflect import annotate_reflect_enabled
from doci.workflows.models import WorkflowInput
from uuid import uuid4


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_env_gate(monkeypatch, value, expected):
    monkeypatch.setenv("DOCI_ANNOTATE_REFLECT", value)
    assert annotate_reflect_enabled() is expected


def test_env_gate_unset(monkeypatch):
    monkeypatch.delenv("DOCI_ANNOTATE_REFLECT", raising=False)
    assert annotate_reflect_enabled() is False


def test_workflow_input_roundtrips_annotate_reflect():
    inp = WorkflowInput(document_id=uuid4(), annotate_reflect=True)
    assert WorkflowInput.from_json(inp.to_json()).annotate_reflect is True


def test_workflow_input_old_blob_defaults_reflect_off():
    """A v1.0 blob without annotate_reflect still parses (defaults off)."""
    did = uuid4()
    old = {"version": "v1.0", "document_id": str(did), "dossier_key": None}
    assert WorkflowInput.from_json(old).annotate_reflect is False
