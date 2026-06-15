"""Resolve a workflow's optional ``group_key`` into a :class:`GroupSpec`.

The mining tasks call this once at start to turn the user-supplied dossier
``group_key`` into the small, serializable :class:`GroupSpec` dict threaded
through graph state to the annotate nodes. A missing/unknown key resolves to
``None`` (annotate falls back to generic, non-classifying behavior) rather than
failing the run.
"""

from typing import Any

from doci.activities.fields import GroupItemSpec, GroupSpec
from doci.userdata import DocumentGroupService, NotFound


async def resolve_group_spec(
    groups: DocumentGroupService, group_key: str | None
) -> dict[str, Any] | None:
    """Fetch ``group_key`` and build a GroupSpec dict, or ``None`` if absent."""
    if not group_key:
        return None
    try:
        group = await groups.get_group(group_key)
    except NotFound:
        return None
    spec = GroupSpec(
        key=group.key,
        name=group.name,
        items=[
            GroupItemSpec(
                key=item.key,
                name=item.name,
                description=item.description,
                fields=item.fields,
            )
            for item in group.items
        ],
    )
    return spec.model_dump()
