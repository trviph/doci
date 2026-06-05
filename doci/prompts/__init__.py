"""Markdown prompt templates, loaded from this package's ``*.md`` files."""

from importlib.resources import files


def load(name: str) -> str:
    """Return the text of ``doci/prompts/<name>.md``."""
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


__all__ = ["load"]
