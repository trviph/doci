"""Markdown prompt templates, loaded from this package's ``*.md`` files."""

from importlib.resources import files


def load(name: str) -> str:
    """Return the text of ``doci/prompts/<name>.md``."""
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def output_language_directive(language: str) -> str:
    """A system-prompt addendum fixing the *output* language + writing style.

    Appended to the audit agents' system prompts so findings and verdicts read
    as fluent prose in ``language`` (default English). Source-language-agnostic:
    the dossier is user-provided data in an unknown language, so only the agent's
    own explanation is rewritten — verbatim evidence quotes stay as-is.
    """
    return (
        "\n\n## Output language and writing style\n\n"
        f"The dossier, its rules, and the reference knowledge are user-provided "
        f"data, in whatever language they happen to be — read them as data, not as "
        f"a cue for your own language. Write every finding message and verdict "
        f"rationale you record in fluent, natural, grammatically correct {language}, "
        f"as well-formed Markdown prose: complete sentences, not terse fragments or "
        f"telegraphic notes. Keep verbatim evidence quotes (the `source` strings and "
        f"any cited wording) in their original language — translate or paraphrase "
        f"only your own explanation. Keep proper nouns, codes, and amounts exactly "
        f"as they appear."
    )


__all__ = ["load", "output_language_directive"]
