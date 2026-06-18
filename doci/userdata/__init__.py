"""User data layer: org-provided definitions an agent consults.

Each concern is a self-contained submodule, imported directly:

- :mod:`doci.userdata.dossiers` — dossier definitions
- :mod:`doci.userdata.documents` — document definitions (m‑1 to a dossier)
- :mod:`doci.userdata.rules` — agent rules (+ m‑n link to dossiers)
- :mod:`doci.userdata.knowledge` — natural-language reference material

Shared helpers live in :mod:`doci.userdata.common` and :mod:`doci.userdata.errors`.
"""
