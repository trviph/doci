import uuid
import os
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

try:
    with _PYPROJECT.open("rb") as f:
        _PACKAGE_VERSION = tomllib.load(f)["project"]["version"]
except OSError, KeyError:
    _PACKAGE_VERSION = "0.1.0"

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
RUNTIME_ID = uuid.uuid4().hex
SERVICE_VERSION = os.getenv("SERVICE_VERSION", _PACKAGE_VERSION)
