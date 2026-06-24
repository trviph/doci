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
        f"the way a human reviewer would explain the outcome to a colleague — "
        f"substantive prose, not a log or a data dump.\n\n"
        "**Never let the machinery show.** These texts are read by people who do "
        "not know how the audit runs internally. Do not put any of the following "
        "into a finding message or verdict rationale:\n\n"
        "- tool names or function-call / arrow syntax — never write things like "
        "`some_check(x) -> value: false`;\n"
        "- internal result or field keys (`ok`, `present`, `match`, `span`, "
        "`diff`, `allowed`, `item_key`, and the like), or raw extracted field "
        "labels copied verbatim as if they were machine output;\n"
        "- internal status or severity enum tokens dropped in as inline jargon.\n\n"
        "Say what those things *mean* in plain words instead: a document is \"not "
        "in the dossier\", two amounts \"do not agree\", a gap is \"beyond the "
        "permitted margin\", a check \"could not be completed\". Refer to each "
        "document by its human-readable name, never by an internal key or slug.\n\n"
        "**Use Markdown structure**, not one run-on paragraph and not terse "
        "telegraphic fragments: a short bold lead, `##` headings to group related "
        "points, and bullets for lists of items where a list reads better than a "
        "sentence.\n\n"
        "Keep verbatim evidence quotes (the `source` strings and any cited "
        "wording) in their original language — translate or paraphrase only your "
        "own explanation. Keep proper nouns, codes, and amounts exactly as they "
        "appear."
    )


__all__ = ["load", "output_language_directive"]
