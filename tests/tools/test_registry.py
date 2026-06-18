from doci.tools.check_vat import check_vat_tool
from doci.tools.compare_amount import compare_amount_tool
from doci.tools.fuzzy_match_name import fuzzy_match_name_tool
from doci.tools.registry import ToolRegistry
from doci.tools.validate_tax_id import validate_tax_id_tool


def _registry() -> ToolRegistry:
    return ToolRegistry().add(
        [
            (check_vat_tool, ["vat", "tax", "money"]),
            (validate_tax_id_tool, ["tax", "id"]),
            (compare_amount_tool, ["amount", "money"]),
            (fuzzy_match_name_tool, ["name", "vendor"]),
        ]
    )


def test_search_ranks_by_relevance():
    reg = _registry()
    names = [r["name"] for r in reg.search(["vat"])]
    assert names[0] == "check_vat"


def test_search_multiple_keywords():
    reg = _registry()
    names = [r["name"] for r in reg.search(["tax", "money"])]
    # check_vat hits both vat/tax + money; ranks above name-matcher
    assert "check_vat" in names[:2] and "fuzzy_match_name" not in names[:1]


def test_search_no_keywords_lists_all():
    reg = _registry()
    assert len(reg.search([])) == 4


def test_no_match_returns_empty():
    reg = _registry()
    assert reg.search(["nonexistent-xyz"]) == []


def test_tools_resolves_names_skipping_unknown():
    reg = _registry()
    tools = reg.tools(["check_vat", "does-not-exist"])
    assert len(tools) == 1 and tools[0].name == "check_vat"
